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


def cargar_estado():
    if not ARCHIVO_ESTADO.exists():
        return {}

    with ARCHIVO_ESTADO.open(encoding="utf-8") as archivo:
        estado = json.load(archivo)

    if not isinstance(estado, dict):
        raise ValueError("El archivo de estado no es válido.")

    return estado


def guardar_estado(estado):
    # Guardado atómico para evitar archivos incompletos.
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=".",
        delete=False,
    ) as archivo:
        json.dump(estado, archivo, ensure_ascii=False, indent=2)
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
            peticion, timeout=30
        ) as respuesta:
            resultado = json.load(respuesta)

        if not resultado.get("ok"):
            raise ValueError("Envío rechazado.")
    except Exception:
        # No mostramos excepciones que puedan contener el token.
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
        raise RuntimeError("No se recibió respuesta de la página.")

    print(f"Respuesta HTTP: {respuesta.status}")

    if respuesta.status >= 400:
        print(f"Título: {pagina.title()}")
        contenido = pagina.locator("body").inner_text(timeout=10000)
        print(f"Respuesta de la página: {contenido[:1500]}")
        raise RuntimeError(
            f"La página devolvió HTTP {respuesta.status}."
        )

    # Solo leemos el estado del producto principal.
    # No buscamos textos de stock por toda la página,
    # porque podrían pertenecer a productos recomendados.
    elemento = pagina.locator(
        '[data-test="product-overview-availability"]'
    )

    elemento.first.wait_for(state="visible", timeout=30000)

    if elemento.count() != 1:
        raise RuntimeError(
            "No se pudo identificar un único estado."
        )

    texto = " ".join(elemento.inner_text().split())

    if not texto or len(texto) > 200:
        raise RuntimeError("El estado leído no es válido.")

    return texto


def main():
    estado = cargar_estado()
    hubo_errores = False

    with sync_playwright() as playwright:
        navegador = playwright.chromium.launch(headless=True)
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
            try:
                actual = consultar_estado(pagina, producto)
                anterior = estado.get(codigo)

                if anterior is None:
                    # Primera consulta: guardamos la referencia
                    # sin enviar una alerta de cambio.
                    estado[codigo] = actual
                    guardar_estado(estado)
                    print(f"{codigo}: estado inicial: {actual}")

                elif actual != anterior:
                    hora = datetime.now(
                        ZoneInfo("Europe/Madrid")
                    ).strftime("%d/%m/%Y %H:%M")

                    enviar_telegram(
                        f"🔔 LEGO {codigo}: {producto['nombre']}\n\n"
                        f"Antes: {anterior}\n"
                        f"Ahora: {actual}\n\n"
                        f"Hora: {hora} (Madrid)\n"
                        f"{producto['url']}"
                    )

                    # Actualizamos solo si se envió la alerta.
                    estado[codigo] = actual
                    guardar_estado(estado)
                    print(f"{codigo}: cambio notificado: {actual}")

                else:
                    print(f"{codigo}: sin cambios: {actual}")

            except Exception as error:
                hubo_errores = True
                print(
                    f"{codigo}: {type(error).__name__}: {error}"
                )
                print("Se conserva el estado anterior.")

        contexto.close()
        navegador.close()

    if hubo_errores:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
