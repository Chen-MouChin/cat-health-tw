# 前端函式庫

| 檔案 | 版本 | 授權 | 來源 |
|---|---|---|---|
| `vue.global.prod.min.js` | Vue 3.4.21 | MIT（Evan You） | https://cdnjs.cloudflare.com/ajax/libs/vue/3.4.21/vue.global.prod.min.js |

放在本機，工作檯在沒有網路的區網也能用。`index.html` 的 `integrity` 是這個檔案的 SHA-384，換版本時要一起更新：

```bash
openssl dgst -sha384 -binary workbench/vendor/vue.global.prod.min.js | openssl base64 -A
```
