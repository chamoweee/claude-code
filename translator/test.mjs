import { test } from "node:test";
import assert from "node:assert/strict";
import { translate, buildSystemPrompt } from "./translate.mjs";

function fakeClient(message, chunks = []) {
  const calls = [];
  return {
    calls,
    beta: { messages: { stream(params) {
      calls.push(params);
      const handlers = {};
      return {
        on(evt, fn) { handlers[evt] = fn; return this; },
        async finalMessage() { chunks.forEach((c) => handlers.text?.(c)); return message; },
      };
    } } },
  };
}

test("returns the translated text and streams chunks", async () => {
  const client = fakeClient({ stop_reason: "end_turn", content: [{ type: "text", text: "你好，世界！" }] }, ["你好，", "世界！"]);
  const seen = [];
  const out = await translate("Hello, world!", {}, { client, onText: (t) => seen.push(t) });
  assert.equal(out, "你好，世界！");
  assert.deepEqual(seen, ["你好，", "世界！"]);
  const p = client.calls[0];
  assert.equal(p.model, "claude-opus-5-5");
  assert.equal(p.fallbacks, "default");
  assert.equal(p.messages[0].content, "Hello, world!");
});

test("system prompt reflects options", () => {
  assert.match(buildSystemPrompt(), /Simplified/);
  assert.match(buildSystemPrompt({ traditional: true }), /Traditional/);
  assert.match(buildSystemPrompt({ pinyin: true }), /pinyin/);
  assert.match(buildSystemPrompt({ tone: "formal" }), /formal register/);
});

test("refusal becomes a clear error", async () => {
  const client = fakeClient({ stop_reason: "refusal", stop_details: { explanation: "x" }, content: [] });
  await assert.rejects(translate("hi", {}, { client }), /declined/);
});
