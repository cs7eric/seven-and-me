# Montserrat 字体文件

把以下两个 `.ttf` 放到本目录（`frontend/public/fonts/montserrat/`）：

- `Montserrat-Regular.ttf` （font-weight 400）
- `Montserrat-Bold.ttf`    （font-weight 700）

## 下载源

- Google Fonts: <https://fonts.google.com/specimen/Montserrat>
- 官方 GitHub: <https://github.com/JulietaUla/Montserrat>

## 路径说明

- Vite dev server 直接以 `/fonts/montserrat/...` 提供
- Vite build 会把它复制到 `dist/`，Flask 再从 `static/` 暴露给 prod
- 如果 prod 用单独的 Flask static 部署，需要把这两个文件也同步到 `static/fonts/montserrat/`

## 缺失文件时

CSS 里的 `font-family` 链会自动回退到 `-apple-system` / `SF Pro` / `Segoe UI` / `PingFang SC` / `Microsoft YaHei`，不会报错。
