import os
import io
from datetime import datetime
from typing import List, Dict, Any

from fastapi import FastAPI, Depends, HTTPException, Header, Request, status, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func
import qrcode

from database import engine, Base, get_db
import models
import schemas

# Create database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="ScreenTime Tracker API",
    description="Servidor de monitoreo de tiempo en pantalla de dispositivos móviles",
    version="1.0.0"
)

# Gestor de conexiones WebSocket para actualización en tiempo real
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, data: dict):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(data)
            except Exception:
                self.disconnect(connection)

manager = ConnectionManager()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static folder
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

def render_template(template_name: str, request: Request, context: dict = None):
    """Renderiza plantillas Jinja2 compatible con todas las versiones de Starlette / FastAPI."""
    ctx = context.copy() if context else {}
    ctx["request"] = request
    try:
        # Compatible con Starlette 0.36+ / FastAPI moderna
        return templates.TemplateResponse(request=request, name=template_name, context=ctx)
    except TypeError:
        # Compatible con Starlette antigua
        return templates.TemplateResponse(template_name, ctx)

# Configurable Security API Key
API_KEY = os.getenv("API_KEY", "screentime_secure_key_2026")
APK_PATH = os.path.join("static", "app.apk")

def verify_api_key(x_api_key: str = Header(..., alias="X-API-Key")):
    """Valida la clave secreta para endpoints que reciben datos de la app Android."""
    if x_api_key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Clave API no autorizada o inválida"
        )
    return x_api_key

def format_duration(seconds: float) -> str:
    """Convierte segundos a formato legible: Xh Ym Zs"""
    s = int(seconds)
    hours = s // 3600
    minutes = (s % 3600) // 60
    rem_seconds = s % 60
    if hours > 0:
        return f"{hours}h {minutes}m {rem_seconds}s"
    elif minutes > 0:
        return f"{minutes}m {rem_seconds}s"
    else:
        return f"{rem_seconds}s"

@app.get("/", response_class=HTMLResponse)
async def landing_page(request: Request):
    """Página de inicio con QR para descargar la APK."""
    return render_template("index.html", request)

@app.get("/descargar")
async def download_apk():
    """Descarga directa del archivo APK."""
    if not os.path.exists(APK_PATH):
        return HTMLResponse(
            status_code=404,
            content="""
            <div style="font-family: sans-serif; text-align: center; padding: 50px;">
                <h2>El archivo APK aún no ha sido cargado en el servidor.</h2>
                <p>Por favor, compila el APK en Android Studio y colócalo en la carpeta <code>static/app.apk</code> del servidor.</p>
                <a href="/" style="color: blue;">Volver al inicio</a>
            </div>
            """
        )
    return FileResponse(
        APK_PATH,
        media_type="application/vnd.android.package-archive",
        filename="ScreenTimeTracker.apk"
    )

@app.get("/qr")
async def get_download_qr(request: Request):
    """Genera en tiempo real el código QR apuntando a la URL de descarga."""
    # En Railway o producción, usa la URL base pública
    public_url = os.getenv("PUBLIC_URL")
    if public_url:
        download_url = f"{public_url.rstrip('/')}/descargar"
    else:
        base_url = str(request.base_url).rstrip('/')
        # Si estamos detrás de un proxy HTTPS de Railway, forzar https
        if request.headers.get("x-forwarded-proto") == "https":
            base_url = base_url.replace("http://", "https://")
        download_url = f"{base_url}/descargar"

    qr = qrcode.QRCode(
        version=1,
        box_size=10,
        border=2,
    )
    qr.add_data(download_url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="#0f172a", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Response(content=buf.getvalue(), media_type="image/png")

@app.post("/api/v1/screen-events", status_code=status.HTTP_201_CREATED)
async def register_screen_event(
    event: schemas.ScreenEventCreate,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    """
    Endpoint protegido con API Key.
    Registra cuando el celular se encendió y apagó, calculando el tiempo de uso.
    """
    # 1. Registrar o actualizar dispositivo
    device = db.query(models.Device).filter(models.Device.id == event.device_id).first()
    if not device:
        device = models.Device(
            id=event.device_id,
            model_name=event.model_name or "Android Device",
            last_seen=datetime.utcnow()
        )
        db.add(device)
    else:
        device.last_seen = datetime.utcnow()
        if event.model_name:
            device.model_name = event.model_name

    # 2. Registrar evento de pantalla
    log = models.ScreenLog(
        device_id=event.device_id,
        screen_on_at=event.screen_on_at,
        screen_off_at=event.screen_off_at,
        duration_seconds=event.duration_seconds
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    # Notificar a los navegadores conectados en tiempo real
    await manager.broadcast({
        "type": "NEW_SESSION",
        "device_id": log.device_id,
        "model_name": device.model_name,
        "screen_on_at": log.screen_on_at.strftime("%Y-%m-%d %H:%M:%S"),
        "screen_off_at": log.screen_off_at.strftime("%Y-%m-%d %H:%M:%S"),
        "duration_seconds": log.duration_seconds,
        "duration_formatted": format_duration(log.duration_seconds)
    })

    return {
        "status": "success",
        "message": "Evento registrado correctamente",
        "log_id": log.id,
        "duration_seconds": log.duration_seconds
    }

@app.websocket("/ws/dashboard")
async def websocket_dashboard_endpoint(websocket: WebSocket):
    """Canal WebSocket para recibir actualizaciones instantáneas en el dashboard."""
    await manager.connect(websocket)
    try:
        while True:
            # Mantener conexión viva
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)

@app.get("/api/v1/dashboard-data")
async def get_dashboard_data(db: Session = Depends(get_db)):
    """Devuelve los datos del dashboard en JSON para actualización fluida."""
    devices = db.query(models.Device).order_by(models.Device.last_seen.desc()).all()
    
    device_summaries = []
    grand_total_seconds = 0.0

    for d in devices:
        total_time = db.query(func.coalesce(func.sum(models.ScreenLog.duration_seconds), 0.0))\
                       .filter(models.ScreenLog.device_id == d.id).scalar()
        total_unlocks = db.query(func.count(models.ScreenLog.id))\
                          .filter(models.ScreenLog.device_id == d.id).scalar()
        
        grand_total_seconds += float(total_time)
        
        device_summaries.append({
            "id": d.id,
            "model_name": d.model_name,
            "total_screen_time_seconds": total_time,
            "total_screen_time_formatted": format_duration(total_time),
            "total_unlocks": total_unlocks,
            "last_seen": d.last_seen.strftime("%Y-%m-%d %H:%M:%S")
        })

    recent_logs_query = db.query(models.ScreenLog).order_by(models.ScreenLog.id.desc()).limit(20).all()
    recent_logs = [
        {
            "id": l.id,
            "device_id": l.device_id,
            "screen_on_at": l.screen_on_at.strftime("%Y-%m-%d %H:%M:%S"),
            "screen_off_at": l.screen_off_at.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_seconds": l.duration_seconds,
            "duration_formatted": format_duration(l.duration_seconds)
        }
        for l in recent_logs_query
    ]
    total_sessions = db.query(func.count(models.ScreenLog.id)).scalar()

    return {
        "devices": device_summaries,
        "recent_logs": recent_logs,
        "total_sessions": total_sessions,
        "grand_total_time": format_duration(grand_total_seconds)
    }

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_view(request: Request, db: Session = Depends(get_db)):
    """Vista web con estadísticas en tiempo real."""
    devices = db.query(models.Device).order_by(models.Device.last_seen.desc()).all()
    
    device_summaries = []
    grand_total_seconds = 0.0

    for d in devices:
        total_time = db.query(func.coalesce(func.sum(models.ScreenLog.duration_seconds), 0.0))\
                       .filter(models.ScreenLog.device_id == d.id).scalar()
        total_unlocks = db.query(func.count(models.ScreenLog.id))\
                          .filter(models.ScreenLog.device_id == d.id).scalar()
        
        grand_total_seconds += float(total_time)
        
        device_summaries.append({
            "id": d.id,
            "model_name": d.model_name,
            "total_screen_time_seconds": total_time,
            "total_screen_time_formatted": format_duration(total_time),
            "total_unlocks": total_unlocks,
            "last_seen": d.last_seen
        })

    recent_logs = db.query(models.ScreenLog).order_by(models.ScreenLog.id.desc()).limit(20).all()
    total_sessions = db.query(func.count(models.ScreenLog.id)).scalar()

    return render_template(
        "dashboard.html",
        request,
        {
            "devices": device_summaries,
            "recent_logs": recent_logs,
            "total_sessions": total_sessions,
            "grand_total_time": format_duration(grand_total_seconds)
        }
    )
