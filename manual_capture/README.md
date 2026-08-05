# GoodJobAI 手动收录岗位

只实现“闭环 1：手动收录岗位”的本地工作区。

启动：

```powershell
D:\ANACONDA\python.exe -m uvicorn manual_capture.app:app --app-dir D:\CODEX\LLMcampus --reload
```

访问 `http://127.0.0.1:8000`。数据保存在本目录的 `campusai_manual.db`。
