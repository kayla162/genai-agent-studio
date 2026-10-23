# Gemini 回應（respx 重播）

`tests/test_gemini_client.py` 以 respx 重播這些 `generateContent`／`models.get` 的 REST 回應（`{ status, body }`）。

- 目前的檔案依 Gemini REST API 的格式手寫（撰寫時還沒有 API key）。
- 有 key 之後，以 `uv run python -m scripts.record_gemini` 呼叫真 API 重新錄製成功的回應（會移除 key 與無關的標頭）；
  錯誤回應（429、503、400、403、404）與安全性過濾維持手寫。
- `ok.json` 與 `invalid.json` 的內容對應測試用的小模型（`headline`、`points`），不是正式的提示詞。
- `brief-ok.json`、`spec-ok.json`、`vlm-ok.json` 是三種正式呼叫的回應（`BriefDraft`、`SpecDraft`、`VlmVerdict`），
  2026-10-23 以 `scripts.record_gemini` 錄製（SÉLUNE 的精華液、IG 貼文）。
- `error-429-daily.json` 是 2026-10-23 實際收到的回應：免費方案每天 20 次的配額用完（不重試）。
