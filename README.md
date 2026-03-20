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
  - [🏪 App Market](#-app-market)
  - [📊 Built-in Apps](#-built-in-apps)
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

### 🏪 App Market

Publish your apps to a shared marketplace. Other users can discover, browse, and add public apps to their own workspace with one click.

![App Market](/assets/feature-market.png)

<div align="right">

[![Back to top][back-to-top]](#readme-top)

</div>

### 📊 Built-in Apps

Comes with ready-to-use apps out of the box:

- **Excel Analyzer** — Upload Excel files for AI-powered data analysis and chart generation
- **RAG Reader** — Upload documents for AI-powered reading and question answering

![Built-in Apps](/assets/feature-builtin.png)

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
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
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
│   │   ├── code_agent.py       # Main agentic loop with tool use
│   │   └── pi-worker/          # TypeScript agent runner
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
2. The **Coding Agent** receives the prompt and uses tools (read, write, bash, edit) to scaffold the app
3. A new sub-app directory is created under `backend/apps/<app_id>/`
4. The app is registered in the database and immediately available in the UI
5. Users can iterate on the app with natural language edits

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
git clone https://github.com/<your-username>/openshrimp.git

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
