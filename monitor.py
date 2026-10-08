import json
import os
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright


PRODUCTOS = {
    "21353": {
        "nombre": "Jardín Botánico",
        "url": (
            "https://www.lego.com/es-es/product/"
            "the-botanical-garden-21353"
        ),
    },
    "76294": {
        "nombre": "X-Men: Mansión X",
        "url": (
            "https://www.lego.com/es-es/product/"
            "x-men-the-x-mansion-76294"
        ),
    },
}

ARCHIVO_ESTADO = Path("estado.json")
SELECTOR_ESTADO = '[data-test="product-overview-availability"]'


def cargar_estado():
    if not ARCHIVO_ESTADO.exists():
        return {}

    with ARCHIVO_ESTADO.open(encoding="utf-8") as archivo:
        estado = json.load(archivo)

    if not isinstance(estado, dict):
        raise ValueError("El archivo de estado no es válido.")

    return estado


def guardar_estado(estado):
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=".",
        delete=False,
    ) as archivo:
        json.dump(
            estado,
            archivo,
            ensure_ascii=False,
            indent=2,
        )
        archivo.write("\n")
        temporal = archivo.name

    os.replace(temporal, ARCHIVO_ESTADO)


def enviar_telegram(texto):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    datos = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": texto,
        "disable_web_page_preview": "true",
    }).encode()

    peticion = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=datos,
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            peticion,
            timeout=30,
        ) as respuesta:
            resultado = json.load(respuesta)

        if not resultado.get("ok"):
            raise ValueError("Envío rechazado.")

    except Exception:
        # Evitamos mostrar errores que puedan contener el token.
        raise RuntimeError(
            "No se pudo enviar la alerta a Telegram."
        ) from None


def consultar_estado(pagina, producto):
    respuesta = pagina.goto(
        producto["url"],
        wait_until="domcontentloaded",
        timeout=60000,
    )

    if respuesta is None:
        raise RuntimeError(
            "No se recibió respuesta de la página."
        )

    http_inicial = respuesta.status
    print(f"HTTP inicial: {http_inicial}", flush=True)

    # No abortamos inmediatamente por el HTTP inicial.
    # Esperamos el campo del producto, igual que en la prueba.
    elemento = pagina.locator(SELECTOR_ESTADO)

    try:
        elemento.first.wait_for(
            state="visible",
            timeout=30000,
        )
    except Exception:
        try:
            titulo = pagina.title()
        except Exception:
            titulo = "No se pudo obtener el título"

        raise RuntimeError(
            "No apareció el campo de disponibilidad "
            "en 30 segundos. "
            f"HTTP inicial: {http_inicial}. "
            f"Título final: {titulo}"
        ) from None

    if elemento.count() != 1:
        raise RuntimeError(
            "No se pudo identificar un único estado."
        )

    texto = " ".join(elemento.inner_text().split())

    if not texto or len(texto) > 200:
        raise RuntimeError(
            "El estado leído no es válido."
        )

    print(f"Estado leído: {texto}", flush=True)
    return texto


def main():
    estado = cargar_estado()
    hubo_errores = False

    with sync_playwright() as playwright:
        navegador = playwright.chromium.launch(
            headless=True,
        )

        try:
            contexto = navegador.new_context(
                locale="es-ES",
                timezone_id="Europe/Madrid",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/153.0.0.0 Safari/537.36"
                ),
            )

            pagina = contexto.new_page()

            for codigo, producto in PRODUCTOS.items():
                print(
                    f"\nConsultando {codigo}...",
                    flush=True,
                )

                try:
                    actual = consultar_estado(
                        pagina,
                        producto,
                    )
                    anterior = estado.get(codigo)

                    if anterior is None:
                        # Primera lectura: referencia sin alerta.
                        estado[codigo] = actual
                        guardar_estado(estado)
                        print(
                            f"{codigo}: estado inicial: {actual}",
                            flush=True,
                        )

                    elif actual != anterior:
                        hora = datetime.now(
                            ZoneInfo("Europe/Madrid")
                        ).strftime("%d/%m/%Y %H:%M")

                        enviar_telegram(
                            f"🔔 LEGO {codigo}: "
                            f"{producto['nombre']}\n\n"
                            f"Antes: {anterior}\n"
                            f"Ahora: {actual}\n\n"
                            f"Hora: {hora} (Madrid)\n"
                            f"{producto['url']}"
                        )

                        # Guardamos solo después del envío correcto.
                        estado[codigo] = actual
                        guardar_estado(estado)

                        print(
                            f"{codigo}: cambio notificado: {actual}",
                            flush=True,
                        )

                    else:
                        print(
                            f"{codigo}: sin cambios: {actual}",
                            flush=True,
                        )

                except Exception as error:
                    hubo_errores = True
                    print(
                        f"{codigo}: "
                        f"{type(error).__name__}: {error}",
                        flush=True,
                    )
                    print(
                        "No se confirma un nuevo estado "
                        "para este producto.",
                        flush=True,
                    )

        finally:
            navegador.close()

    if hubo_errores:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
