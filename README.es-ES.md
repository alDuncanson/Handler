

# Handler

[![CI](https://github.com/alDuncanson/handler/actions/workflows/ci.yml/badge.svg)](https://github.com/alDuncanson/handler/actions/workflows/ci.yml)
[![A2A Protocol](https://img.shields.io/badge/A2A_Protocol-v1.0.0-blue)](https://a2a-protocol.org/latest/)
[![PyPI version](https://img.shields.io/pypi/v/a2a-handler)](https://pypi.org/project/a2a-handler/)
[![PyPI - Status](https://img.shields.io/pypi/status/a2a-handler)](https://pypi.org/project/a2a-handler/)
[![Pepy total downloads](https://img.shields.io/pepy/dt/a2a-handler?label=total%20downloads)](https://pepy.tech/projects/a2a-handler)
[![GitHub stars](https://img.shields.io/github/stars/alDuncanson/handler)](https://github.com/alDuncanson/handler/stargazers)

Handler es un cliente de código abierto para el [protocolo A2A](https://github.com/a2aproject/A2A)
destinado a ingenieros de software que construyen, prueban y operan sistemas basados en agentes.
Proporciona una TUI interactiva, una CLI scriptable con salida estructurada y un
servidor MCP que permite a otros agentes integrarse directamente con servicios A2A. Handler
también admite la configuración global y a nivel de repositorio de servidores A2A con autenticación bearer,
clave API, mTLS y credenciales de cliente OAuth2.

![TUI de Handler conectada al Agente Handler integrado, mostrando la tarjeta del agente y una respuesta del asistente completada](https://raw.githubusercontent.com/alDuncanson/Handler/73915875903b60dad6e4e404aa7ed91b6d94559f/assets/tui.png)

## Instalación

Instala Handler desde el [paquete PyPI](https://pypi.org/project/a2a-handler/) como una herramienta `uv`:

```bash
uv tool install a2a-handler
```

O con [pipx](https://pipx.pypa.io/):

```bash
pipx install a2a-handler
```

O con pip:

```bash
pip install a2a-handler
```

## Inicio rápido

Abre la interfaz de terminal interactiva:

```bash
handler tui
```

Inspecciona la tarjeta del agente de un servidor A2A:

```bash
handler card get --url http://localhost:8000
```

Envía un mensaje desde la CLI:

```bash
handler message send --url URL --text "hello"
```

Abre la documentación completa:

```bash
handler docs
```

## Ejecutar sin instalar

Ejecuta Handler con `uvx`:

```bash
uvx --from a2a-handler handler
```

Ejecuta Handler con `pipx`:

```bash
pipx run a2a-handler
```

## Documentación

Lee la documentación en <https://handler.alduncanson.com>.
