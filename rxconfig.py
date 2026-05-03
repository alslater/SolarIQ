import reflex as rx

config = rx.Config(
    app_name="solariq",
    port=3002,
    show_built_with_reflex=False,
    stylesheets=["compli.css"],
    disable_plugins=[rx.plugins.SitemapPlugin]
)
