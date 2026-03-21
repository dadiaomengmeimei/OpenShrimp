<div align="center"><a name="readme-top"></a>

# 🦐 OpenShrimp

An open-source AI-powered App Store platform.<br/>
Describe your app in one sentence, and AI generates the full-stack code instantly.<br/>
Create, manage, publish, and share AI applications — all from a single platform.

<!-- SHIELD GROUP -->

[![License badge][license-shield]][license-link]
![Last Commit badge][last-commit-shield]
[![Issues badge][issues-shield]][issues-link]
[![Stars badge][stars-shield]][stars-link]

</div>

![OpenShrimp Banner](/assets/banner.png)

<details>
<summary><kbd>Table of contents</kbd></summary>

#### TOC

- [📺 Demo](#-demo)
- [✨ Features](#-features)
  - [🤖 One-Sentence App Generation](#-one-sentence-app-generation)
  - [✏️ Natural Language App Editing](#️-natural-language-app-editing)
  - [🔧 Auto-Fix (Error & Behavior)](#-auto-fix-error--behavior)
  - [🧠 Skills Memory System](#-skills-memory-system)
  - [🏪 App Market](#-app-market)
  - [📊 Built-in Apps](#-built-in-apps)
  - [🛠️ Agent Toolbox](#️-agent-toolbox)
  - [🗜️ Context Compression](#️-context-compression)
  - [👁️ Real-time Supervision](#️-real-time-supervision)
  - [🔌 Any LLM Provider](#-any-llm-provider)
  - [👥 Multi-User & Auth](#-multi-user--auth)
- [🚀 Getting Started](#-getting-started)
  - [Prerequisites](#prerequisites)
  - [Quick Start](#quick-start)
  - [Docker](#docker)
  - [Configuration](#configuration)
- [🏗️ Architecture](#️-architecture)
- [🤝 Contributing](#-contributing)
- [📜 License](#-license)

<br/>

</details>

## 📺 Demo

![OpenShrimp Demo](/assets/demo.gif)

<div align="center">
  <img src="assets/generate-app-demo.png" width="48%" alt="Generate an app with one sentence" />
  <img src="assets/edit-app-demo.png" width="48%" alt="Edit an app with natural language" />
</div>

<div align="right">

[![Back to top][back-to-top]](#readme-top)

</div>

## ✨ Features

OpenShrimp turns natural language into fully functional AI-powered web applications. No boilerplate, no scaffolding — just describe what you want.

### 🤖 One-Sentence App Generation

Describe your app idea in a single sentence, and OpenShrimp's coding agent generates the entire full-stack application — backend API routes, frontend UI, and database logic — all in seconds.

![One-Sentence Generation](/assets/feature-generate.png)

<div align="right">

[![Back to top][back-to-top]](#readme-top)

</div>

### ✏️ Natural Language App Editing

Already have an app? Tell OpenShrimp what to change in plain language. The AI agent reads your existing code, understands the context, and applies precise modifications — adding features, fixing bugs, or refactoring.

![Natural Language Editing](/assets/feature-edit.png)

<div align="right">

[![Back to top][back-to-top]](#readme-top)

</div>

### 🔧 Auto-Fix (Error & Behavior)

When an app crashes, OpenShrimp automatically catches the runtime error and offers **one-click Auto-Fix**. The agent reads the traceback, analyzes root cause, locates the buggy code, and applies a surgical fix — all without you touching a single line of code.

Even when there's no crash but the output is simply _wrong_, you can use **Behavior Fix** mode: describe what you expected, and the agent compares the actual vs. expected output to understand the gap and rewrite the logic accordingly.

Both modes support **real-time supervision** — you can guide the agent with additional messages during the fix process.

<div align="right">

[![Back to top][back-to-top]](#readme-top)

</div>

### 🧠 Skills Memory System

After every agent session (generation, editing, or debugging), OpenShrimp automatically **extracts reusable skills** from the conversation:

- **User preferences** — what you really wanted, style choices, constraints
- **Debugging lessons** — errors encountered, root causes, how they were fixed
- **Architecture decisions** — why certain patterns were chosen
- **Potential extensions** — features hinted at but not yet built

These skills are persisted per-app and loaded into context for future sessions. The agent gets **smarter with every interaction** — it won't repeat past mistakes and will respect your preferences.

<div align="right">

[![Back to top][back-to-top]](#readme-top)

</div>

### 🏪 App Market

Publish your apps to a shared marketplace. Other users can discover, browse, and add public apps to their own workspace with one click.

![App Market](/assets/feature-market.png)

<div align="right">

[![Back to top][back-to-top]](#readme-top)

</div>

### 📊 Built-in Apps

Comes with ready-to-use apps out of the box:

- **Excel Analyzer** — Upload Excel files for AI-powered data analysis, pivot tables, and chart generation
- **RAG Reader** — Upload documents (PDF, TXT, etc.) for AI-powered reading and question answering with source citations

These built-in apps also serve as reference implementations — the coding agent can use them as templates when generating similar applications.

![Built-in Apps](/assets/feature-builtin.png)

<div align="right">

[![Back to top][back-to-top]](#readme-top)

</div>

### 🛠️ Agent Toolbox

The coding agent is not just a prompt-to-code generator. It has a full **developer toolbox**:

| Tool | Description |
| --- | --- |
| `ls` | Browse directories — understand project structure |
| `read` | Read file contents — analyze existing code |
| `write` | Create new files — scaffold from scratch |
| `edit` | Surgical text replacement — modify without rewriting |
| `bash` | Run shell commands — test, install deps, check output |
| `update_app_features` | Toggle UI capabilities (e.g., enable file upload) |

The agent uses these tools in an **autonomous iterative loop** (up to 200 iterations): write code → execute → check errors → fix → repeat — just like a real developer.

<div align="right">

[![Back to top][back-to-top]](#readme-top)

</div>

### 🗜️ Context Compression

Long agent sessions don't blow up the token budget. Every 5 iterations, OpenShrimp automatically **compresses conversation history** into a structured summary, preserving:

- Original user goal
- Files created or modified
- Key decisions made
- Errors encountered and resolutions
- Current progress state

This allows the agent to run **200+ iterations** on complex tasks without losing context or hitting token limits.

<div align="right">

[![Back to top][back-to-top]](#readme-top)

</div>

### 👁️ Real-time Supervision

You're always in control. While the agent is running:

- **📡 Live SSE Streaming** — Watch every tool call, file modification, and agent thought in real-time
- **📝 Message Injection** — Send guidance messages mid-generation (e.g., _"don't use that library, use X instead"_)
- **⛔ Interrupt** — Stop the agent at any point if it's going off track
- **🔍 Self-Verification** — After generation, the agent automatically validates app structure, Python syntax, and module imports. If checks fail, it triggers an auto-repair loop.

<div align="right">

[![Back to top][back-to-top]](#readme-top)

</div>

### 🔌 Any LLM Provider

Connect to any OpenAI-compatible LLM provider — OpenAI, Moonshot (Kimi), DeepSeek, Anthropic Claude, and more. Configure once in `.env`, and all apps share the same model.

<div align="right">

[![Back to top][back-to-top]](#readme-top)

</div>

### 👥 Multi-User & Auth

Built-in JWT authentication with user registration, login, and role-based access. Each user has their own app workspace while sharing a common marketplace.

<div align="right">

[![Back to top][back-to-top]](#readme-top)

</div>

## 🚀 Getting Started

### Prerequisites

- **Python** 3.10+
- **Node.js** 18+
- An API key from any OpenAI-compatible LLM provider

### Quick Start

1. **Clone the repository**

```bash
git clone https://github.com/anthropics/openshrimp.git
cd openshrimp
```

2. **Configure environment**

```bash
cp .env.example .env
# Edit .env and fill in your LLM API key and base URL
```

3. **Install backend dependencies**

```bash
pip install -r backend/requirements.txt
```

4. **Install frontend dependencies**

```bash
cd frontend
npm install
cd ..
```

5. **Start the backend**

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload --reload-exclude 'backend/apps/*'
```

6. **Start the frontend** (in a new terminal)

```bash
cd frontend
npm run dev
```

7. **Open your browser** at `http://localhost:5173`

> Default admin credentials: `admin` / `admin123`

### Docker

```bash
docker-compose up --build
```

### Configuration

All configuration is managed through the `.env` file:

| Variable | Description | Example |
| --- | --- | --- |
| `LLM_PROVIDER` | LLM provider type | `openai` |
| `LLM_API_KEY` | Your API key | `sk-...` |
| `LLM_API_BASE` | API base URL | `https://api.openai.com/v1` |
| `LLM_MODEL` | Model name | `gpt-4o` |
| `LLM_MAX_TOKENS` | Max output tokens | `20000` |
| `PLATFORM_APP_NAME` | Platform display name | `OpenShrimp` |
| `AUTH_SECRET_KEY` | JWT secret key | (auto-generated if empty) |

<div align="right">

[![Back to top][back-to-top]](#readme-top)

</div>

## 🏗️ Architecture

```
openshrimp/
├── backend/
│   ├── agent/           # AI coding agent (generates & edits apps)
│   │   └── code_agent.py       # Main agentic loop with tool use
│   ├── api/             # Platform REST API routes
│   ├── apps/            # Generated sub-apps (each is a FastAPI router)
│   ├── config/          # Settings & environment config
│   └── core/            # Shared services (LLM, DB, auth, registry)
├── frontend/
│   ├── src/
│   │   ├── pages/       # Login, Home, Market, App pages
│   │   ├── components/  # AgentModal, GenericApp, etc.
│   │   └── services/    # API client
│   └── ...
├── data/                # SQLite DB & generated outputs
├── docker-compose.yml
└── .env                 # All configuration lives here
```

**How it works:**

1. User describes an app in the **AgentModal** (e.g. _"Build a todo list with priorities"_)
2. The **Coding Agent** receives the prompt and uses tools (`ls`, `read`, `write`, `edit`, `bash`) to scaffold the app
3. The agent iterates autonomously — writing code, running tests, fixing errors — up to 200 iterations
4. **Self-verification** checks structure, syntax, and imports; auto-repairs if anything fails
5. A new sub-app directory is created under `backend/apps/<app_id>/` with its own isolated `.venv`
6. Dependencies are auto-detected and installed; the app is registered and immediately available
7. **Skills** are extracted from the session and saved for future context
8. Users can iterate on the app with natural language edits, or use **Auto-Fix** for runtime errors

<div align="right">

[![Back to top][back-to-top]](#readme-top)

</div>

## 🤝 Contributing

Contributions of all types are more than welcome!

1. ⭐ **Star** this repo to show your support
2. 🐛 Report [issues][issues-link] and feedback
3. 🔧 Submit pull requests

```bash
# Fork & clone
git clone https://github.com/dadiaomengmeimei/OpenShrimp.git

# Create a branch
git checkout -b feat/amazing-feature

# Make your changes, then
git commit -m "feat: add amazing feature"
git push origin feat/amazing-feature
```

<div align="right">

[![Back to top][back-to-top]](#readme-top)

</div>

## 📜 License

MIT © OpenShrimp

<div align="right">

[![Back to top][back-to-top]](#readme-top)

</div>

<!-- LINK GROUP -->

[back-to-top]: https://img.shields.io/badge/-BACK_TO_TOP-151515?style=flat-square
[issues-link]: https://github.com/anthropics/openshrimp/issues
[issues-shield]: https://img.shields.io/github/issues/anthropics/openshrimp?style=flat-square&labelColor=black
[last-commit-shield]: https://img.shields.io/github/last-commit/anthropics/openshrimp?style=flat-square&label=commit&labelColor=black
[license-link]: ./LICENSE
[license-shield]: https://img.shields.io/badge/license-MIT-blue?style=flat-square&labelColor=black
[stars-link]: https://github.com/anthropics/openshrimp/stargazers
[stars-shield]: https://img.shields.io/github/stars/anthropics/openshrimp?style=flat-square&label=stars&color=yellow&labelColor=black
