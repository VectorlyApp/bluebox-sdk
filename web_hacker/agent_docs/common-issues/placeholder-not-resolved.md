# Placeholder Not Resolved

> Placeholders like `{{param}}` appear as literal text or resolve to empty values due to missing escape quotes, using storage placeholders in navigate (not supported), wrong storage access in js_evaluate, or incorrect paths. Related: [placeholders.md](../core/placeholders.md), [fetch.md](../operations/fetch.md)

**Symptom:** Literal `{{param}}` appears in request, or value is empty

**Causes & Fixes:**

| Cause | Fix |
|-------|-----|
| String not escape-quoted | Use `"\"{{param}}\""` not `"{{param}}"` |
| Storage placeholder in navigate | Not supported - only user params work in URLs |
| Storage placeholder in js_evaluate | Access directly: `sessionStorage.getItem('key')` |
| Wrong path | Check exact key name and nesting |

**Check what's in storage:**
```javascript
(function() {
  return JSON.parse(sessionStorage.getItem('my_key'));
})()
```
