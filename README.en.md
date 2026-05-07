# Split PDF Handout to Image Slide

[繁體中文](README.md) | [English](README.en.md)

Split a multi-slide PDF handout into a new PDF where each handout cell becomes a single image slide.

This tool is designed for handout PDFs exported from PowerPoint, Keynote, or similar presentation tools. It is useful when a PDF page contains multiple slides, such as 2x2, 3x2, or 3x3 layouts, and you want a mobile- or tablet-friendly PDF with one slide per page.

Project repository: [taoyutsun/split-pdf-handout-to-image-slide](https://github.com/taoyutsun/split-pdf-handout-to-image-slide)

Related article:

[多格講義 PDF 轉單頁投影片工具升級版：Split PDF Handout to Image Slide 正式開源上架 GitHub](https://taoyutsun.blogspot.com/2026/04/split-pdf-handout-to-image-slide-github-release.html)

## Features

- Convert multi-cell PDF handout pages into one-slide-per-page output.
- Support common handout layouts such as 2x2, 3x2, and 3x3.
- Preserve the original slide appearance by rendering each crop as an image.
- Provide both GUI and command-line workflows.
- Support custom output file paths.
- Support optional page/cell reading order settings.

## Download

For general users, download the release package from GitHub Releases:

[https://github.com/taoyutsun/split-pdf-handout-to-image-slide/releases](https://github.com/taoyutsun/split-pdf-handout-to-image-slide/releases)

If a packaged Windows executable is available in the release, use it directly. Otherwise, run the project from source with Python.

## GUI Usage

1. Open the application.
2. Select the source handout PDF.
3. Choose the layout, such as 2x2 or 3x2.
4. Choose the output location.
5. Start conversion.

The output is a new PDF where each extracted handout cell becomes an individual page.

## Run From Source

Clone the repository:

```powershell
git clone https://github.com/taoyutsun/split-pdf-handout-to-image-slide.git
cd split-pdf-handout-to-image-slide
```

Install the required Python packages according to the project files, then run the script.

Example:

```powershell
python .\split_pdf_handout_to_image_slide_optimized.py ".\handout.pdf"
```

Specify an output file:

```powershell
python .\split_pdf_handout_to_image_slide_optimized.py ".\handout.pdf" -o ".\handout_slide.pdf"
```

Specify reading order or layout options if needed:

```powershell
python .\split_pdf_handout_to_image_slide_optimized.py ".\handout.pdf" --order 2
python .\split_pdf_handout_to_image_slide_optimized.py ".\handout.pdf" --layout 2x2
```

## Poppler

Some PDF rendering flows may require Poppler. If conversion fails because PDF rendering tools are missing, install Poppler and make sure the executable path is available to the application.

## Build A Windows EXE

If you want to package the tool yourself, use the project build script or PyInstaller configuration included in the repository. The exact command may depend on your local Python environment.

## Known Limits

- The tool assumes the source PDF pages have a consistent handout layout.
- Complex PDFs or unusual crop margins may need manual adjustment.
- The output pages are image-based, so text selection may not be preserved.

## License

See the repository license for details.
