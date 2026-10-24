# 品牌的多組視覺風格（visualStyles）設計規格（已確認）

## 1. 目標

一個品牌可以設定多組背景風格（例如「日常」「節慶」「科研」），建立任務時選一組，或由系統依語氣自動選擇。選定的風格取代現在唯一的 `visualStyle`，放進 ComfyUI 的正向提示詞。

## 2. 品牌設定檔

```yaml
visualStyles:
  - id: daily
    label: 日常
    prompt: soft lavender gradient, satin fabric, glossy acrylic podium
    tones: [gentle, minimal]
  - id: festive
    label: 節慶
    prompt: champagne gold confetti, ribbon, warm bokeh, celebratory set
    tones: [playful]
  - id: lab
    label: 科研
    prompt: clean glass shelves, water ripples, cool soft light, clinical white set
    tones: [science]
```

- `id`：小寫英文、數字與連字號，品牌內不可重複；`label`：前端顯示的名稱。
- `prompt`：英文，放進正向提示詞（與現在的 `visualStyle` 相同）。
- `tones`：自動選擇時對應的語氣（gentle、science、playful、minimal），可省略。
- 不再支援舊的 `visualStyle: 字串`：三個品牌設定檔與範本一起改成新格式；設定檔仍寫 `visualStyle` 時載入失敗並說明改用 `visualStyles`。
- 至少一組，最多 6 組。

## 3. 任務

- `JobInput` 新增 `visualStyleId: string | null`；`null` 為自動。
- 自動：第一組 `tones` 含需求語氣（`parsedBrief.tone`）的風格；都沒有時用第一組。
- 選定的風格在任務開頭寫一則 log（Agent 透視的 log 面板），例如「背景風格：節慶（自動：語氣 playful）」「背景風格：科研（指定）」；選定的提示詞出現在每個模板的 positive prompt。
- 建立任務時檢查 `visualStyleId` 是品牌的其中一組（後端與 mock 相同），不是時回 400「品牌沒有這個背景風格：…」。
- 需求裡的風格（`parsedBrief.style`）照舊附加在後面。
- 同一個任務的所有模板、所有候選與重試的每一輪都用同一組風格。

## 4. 前端

- 新任務表單在模板選擇附近加「背景風格」下拉選單：自動（預設）＋各組名稱。
- 品牌知識庫的品牌總覽列出每一組的名稱、語氣與提示詞。
- mock 模式的兩個示範品牌各加 2–3 組，作品集 Demo 也能操作。

## 5. 相容與測試

- 合約（`contract.ts`、`contract.py`）的 `Brand.visualStyle` 改為 `visualStyles`；golden fixtures 與 timelines 隨之更新。
- 測試：設定檔載入（新格式、仍寫舊欄位、id 重複、0 組或超過 6 組）、自動選擇、提示詞內容、前端選單、mock 流程。

## 6. 已確認的決定（2026-10-24）

| 項目 | 決定 |
|---|---|
| 選擇方式 | 可手選，預設自動（依需求語氣） |
| 多張候選 | 同一個任務全部用同一組 |
| 舊格式 | 不保留，品牌設定檔全部改成 `visualStyles` |

## 7. 實作時的調整

- **不在 `PromptSpec` 加欄位**：改以任務開頭的 log 顯示選定的風格，PromptSpec 與合規報告的格式不變。選定風格的 id 經 `SpecRequest`（後端）與 `PromptBuildInput`／`GuardRequest`（composer）傳遞，Gemini 的品牌資料 `visualStyle` 為選定那一組的提示詞。
- **選擇規則寫兩份**：`web/src/lib/agent/style.ts` 與 `backend/app/visual_style.py`，兩邊的測試用相同的情況與說明文字。
- **示範品牌**：每個品牌的第一組沿用原本的提示詞（SÉLUNE「月光柔霧」、misty-isle「晨霧咖啡館」），既有的示範任務提示詞不變；只有 `selune-needs-review`（語氣 science）自動改用「科研」。
- **Kayla 精緻少女**：原本的範本提示詞含 product photography（會多畫出其他商品），換成日常、節慶、科研三組。
- **驗證**：後端 412 個測試、前端 612 個測試、typecheck、lint、build、`demo:check` 通過；mock E2E 10 次中 2 次在「任務選單」的時間判斷失敗，main 在同樣負載下結果相同（既有的不穩定）。live：未知的風格回 400；指定「節慶」的任務 log 為「背景風格：節慶（指定）」，positive prompt 含節慶的提示詞，任務完成。
