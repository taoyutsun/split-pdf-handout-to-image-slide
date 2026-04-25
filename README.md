# Split PDF Handout to Image Slide

將「一頁多格」的 PDF 講義拆成適合逐頁閱讀的單張投影片 PDF。

這個工具適合處理由 PowerPoint、Keynote 或其他簡報軟體匯出的 handout PDF，例如 2x2、3x2、3x3 等多格講義。轉換後會輸出新的單頁投影片 PDF，方便在電腦、平板或手機上閱讀。

原始介紹文章：[讓多格講義 PDF 瞬間變身好閱讀的逐頁投影片](https://taoyutsun.blogspot.com/2025/03/split-pdf-handout-to-image-slide.html)

## 功能特色

- 自動偵測多格講義中的投影片區塊。
- 支援「左到右，再上到下」與「上到下，再左到右」兩種排列順序。
- 可直接輸出單一 PDF。
- 可使用圖形介面操作，也可使用命令列批次轉換。
- 自動偵測失敗時，可指定固定版面，例如 `2x2`、`3x2`、`2x3`。
- 預設不覆蓋既有檔案，會自動產生新的輸出檔名。

## GitHub 下載

請到 GitHub 專案頁的 **Releases** 下載最新版本。

一般使用者建議下載：

```text
split_pdf_handout_to_image_slide_optimized.exe
```

下載後直接雙擊執行即可，不需要另外安裝 Python。

想檢視或修改程式碼的使用者，可下載原始碼，或直接 clone repository：

```powershell
git clone https://github.com/taoyutsun/split-pdf-handout-to-image-slide.git
cd split-pdf-handout-to-image-slide
```

## GUI 操作方式

開啟程式後，依序操作：

1. 按「選擇 PDF」，或直接將 PDF 拖曳到視窗中的檔案區域。
2. 若需要指定輸出位置，可按「儲存為」；若留空，程式會自動輸出到原 PDF 同一資料夾。
3. 選擇排列順序：
   - `左到右，再上到下`：一般 2x2、3x2 講義常用。
   - `上到下，再左到右`：適合某些特殊列印順序。
4. 選擇版面模式：
   - `auto`：自動偵測，建議先使用此模式。
   - `2x2`、`3x2`、`2x3` 等：自動偵測不理想時，可手動指定固定版面。
5. 按「開始轉換」。
6. 轉換完成後，可按「開啟輸出資料夾」查看結果。

輸出檔預設命名為：

```text
原始檔名_slide.pdf
```

如果同名檔案已存在，程式會自動加編號，避免覆蓋既有檔案。

## 進階設定：Poppler

Poppler 是程式用來讀取與轉換 PDF 的外部工具。一般使用 exe 版本時，通常不需要手動設定。

只有在程式提示找不到 Poppler、無法讀取 PDF 時，才需要到「顯示進階設定」指定 Poppler 的 `bin` 資料夾。

常見路徑範例：

```powershell
C:\poppler-24.08.0\Library\bin
```

可用的設定方式：

- 將 Poppler 的 `bin` 資料夾加入系統 `PATH`。
- 設定環境變數 `PDF2IMAGE_POPPLER_PATH`。
- 在 GUI 的進階設定中指定 Poppler 路徑。
- 命令列執行時使用 `--poppler-path` 指定路徑。

參考：[`pdf2image` 官方文件](https://pdf2image.readthedocs.io/en/latest/reference.html) 與 [`pdf2image` GitHub](https://github.com/Belval/pdf2image)。

## 從原始碼執行

建議在 Windows 原生環境執行。GUI 使用 Python 內建 Tkinter，拖曳功能使用 `tkinterdnd2`。

安裝依賴：

```powershell
pip install -r requirements.txt
```

啟動 GUI：

```powershell
python .\split_pdf_handout_to_image_slide_optimized.py
```

## 命令列用法

基本轉換：

```powershell
python .\split_pdf_handout_to_image_slide_optimized.py ".\handout.pdf"
```

指定輸出檔：

```powershell
python .\split_pdf_handout_to_image_slide_optimized.py ".\handout.pdf" -o ".\handout_slide.pdf"
```

使用欄優先順序：

```powershell
python .\split_pdf_handout_to_image_slide_optimized.py ".\handout.pdf" --order 2
```

指定固定版面：

```powershell
python .\split_pdf_handout_to_image_slide_optimized.py ".\handout.pdf" --layout 2x2
```

保留拆出的中間圖片：

```powershell
python .\split_pdf_handout_to_image_slide_optimized.py ".\handout.pdf" --keep-images
```

指定 Poppler：

```powershell
python .\split_pdf_handout_to_image_slide_optimized.py ".\handout.pdf" --poppler-path "C:\poppler-24.08.0\Library\bin"
```

## 自行打包 exe

若想從原始碼自行打包 Windows exe，可使用 PyInstaller：

```powershell
pip install pyinstaller
pyinstaller --onefile --windowed --collect-data tkinterdnd2 .\split_pdf_handout_to_image_slide_optimized.py
```

打包完成後，exe 會出現在 `dist` 資料夾。

若希望 exe 在沒有系統 Poppler 設定的電腦上也能使用，可將 Poppler 放在 exe 同層的以下任一路徑：

```text
poppler\Library\bin
poppler\bin
```

## 已知限制

- 若 PDF 不是標準簡報 handout 格式，或投影片之間沒有清楚分隔，自動偵測可能需要改用固定版面。
- 若來源 PDF 解析度太低，輸出品質也會受限制。
- 大型 PDF 轉換需要較長時間。

## 授權

MIT License
