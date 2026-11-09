import os
import uvicorn

if __name__ == "__main__":
    # Obtener el puerto que Railway asigna automáticamente
    port = int(os.environ.get("PORT", 8000))
    print(f"Iniciando servidor ScreenTime en el puerto {port}...")
    uvicorn.run("main:app", host="0.0.0.0", port=port)
