# English → Chinese translator

A small command-line translator powered by Claude (`claude-opus-5-5`).

## Setup

```bash
cd translator
npm install
export ANTHROPIC_API_KEY=sk-ant-...   # from https://console.anthropic.com
```

## Use

```bash
node translate.mjs "The early bird catches the worm."     # → 早起的鸟儿有虫吃。
node translate.mjs -t "Welcome to our store"              # Traditional characters (繁體)
node translate.mjs -p "Nice to meet you"                  # add pinyin
node translate.mjs --tone business "Please find attached the invoice."
node translate.mjs -f letter.txt > letter.zh.txt          # translate a file
echo "Good morning" | node translate.mjs                  # pipe text in
node translate.mjs                                        # interactive mode
```

Tones: `neutral` (default), `formal`, `casual`, `business`, `technical`.

## Use it from your own code

```js
import { translate } from "./translate.mjs";
const zh = await translate("How much is this?", { traditional: false, tone: "casual" });
```

## Notes

- Output streams as it is generated, so long texts appear right away.
- Formatting (Markdown, lists, code, URLs) is kept as is.
- Effort is set to `low`, which is fast and cheap and fine for translation. Raise it in
  `translate.mjs` for literary or legal text.
- If the model declines a request, it is retried on a fallback model on the server
  (`fallbacks: "default"`).
- `npm test` runs offline tests that need no API key.
