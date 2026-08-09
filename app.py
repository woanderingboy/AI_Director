import os
from web import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # 调试模式默认关闭：避免 Werkzeug 交互式控制台在 0.0.0.0 暴露。
    # 本地开发需调试时设 FLASK_DEBUG=1。
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(debug=debug, host="0.0.0.0", port=port)
