import reflex as rx

config = rx.Config(
    app_name="solariq",
    frontend_port=3002,
    backend_port=8002,
    stylesheets=["compli.css"],
    disable_plugins=[rx.plugins.SitemapPlugin]
)
