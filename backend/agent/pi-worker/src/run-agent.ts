/**
 * Pi Coding Agent Runner (streaming mode)
 *
 * Receives a JSON request on stdin.
 * Streams events to stdout as JSON-lines (one JSON object per line).
 * Final result is a JSON line with type "done" or "error".
 *
 * Event types:
 *   { type: "log", message: "..." }
 *   { type: "text_delta", delta: "..." }
 *   { type: "tool_call", tool: "write", input: {...} }
 *   { type: "tool_result", tool: "write", output: "..." }
 *   { type: "file_modified", path: "..." }
 *   { type: "done", output: "...", files_modified: [...] }
 *   { type: "error", error: "..." }
 */

import {
    createAgentSession,
    createCodingTools,
    AuthStorage,
    InMemoryAuthStorageBackend,
    ModelRegistry,
    SessionManager,
    SettingsManager,
    type ResourceLoader,
    createExtensionRuntime,
    type ExtensionFactory,
} from "@mariozechner/pi-coding-agent";

// Emit a JSON event line to stdout
function emit(event: Record<string, unknown>) {
    process.stdout.write(JSON.stringify(event) + "\n");
}

// Read stdin as JSON
async function readStdin(): Promise<string> {
    const chunks: Buffer[] = [];
    for await (const chunk of process.stdin) {
        chunks.push(chunk);
    }
    return Buffer.concat(chunks).toString("utf-8");
}

interface AgentRequest {
    prompt: string;
    cwd: string;
    app_id?: string;
    llm: {
        api_base: string;
        api_key: string;
        model: string;
    };
}

async function main() {
    let request: AgentRequest;
    try {
        const input = await readStdin();
        request = JSON.parse(input);
    } catch (e) {
        emit({ type: "error", error: `Invalid input: ${e}` });
        process.exit(1);
    }

    const { prompt, cwd, llm } = request;
    emit({ type: "log", message: `Starting pi-coding-agent in ${cwd}` });
    emit({ type: "log", message: `Model: ${llm.model} @ ${llm.api_base}` });

    try {
        // Set up auth storage
        const authStorage = new AuthStorage(new InMemoryAuthStorageBackend());
        authStorage.setRuntimeApiKey("custom-llm", llm.api_key);

        // Create model registry
        const modelRegistry = new ModelRegistry(authStorage, undefined);

        // Register custom OpenAI-compatible provider
        modelRegistry.registerProvider("custom-llm", {
            baseUrl: llm.api_base,
            apiKey: llm.api_key,
            api: "openai-completions",
            models: [
                {
                    id: llm.model,
                    name: llm.model,
                    reasoning: false,
                    input: ["text"] as ("text" | "image")[],
                    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
                    contextWindow: 128000,
                    maxTokens: 20000,
                },
            ],
        });

        const model = modelRegistry.find("custom-llm", llm.model);
        if (!model) {
            throw new Error(`Model not found: ${llm.model}`);
        }
        emit({ type: "log", message: `Model registered: ${model.name}` });

        // Resource loader (no model-specific extensions needed for Kimi)
        const extensionRuntime = createExtensionRuntime();
        const resourceLoader: ResourceLoader = {
            getExtensions: () => ({
                extensions: [],
                errors: [],
                runtime: extensionRuntime,
            }),
            getSkills: () => ({ skills: [], diagnostics: [] }),
            getPrompts: () => ({ prompts: [], diagnostics: [] }),
            getThemes: () => ({ themes: [], diagnostics: [] }),
            getAgentsFiles: () => ({ agentsFiles: [] }),
getSystemPrompt: () => `You are an expert code agent for an AI App Store platform called OpenShrimp.
Your working directory is: ${cwd}
You have access to tools: read (read files), bash (run commands), edit (modify files), write (create files).

Every sub-app lives in its own directory under backend/apps/<app_id>/ and has at minimum:
- __init__.py (can be empty)
- main.py (containing a FastAPI APIRouter and route handlers)

The sub-app can import shared services:
- from backend.core.llm_service import chat_completion, function_call
- from backend.core.asr_service import transcribe

The sub-app's router must use prefix /api/apps/<app_id>.

IMPORTANT rules:
1. Always start by reading the current directory structure (use ls and read tools)
2. Think step by step about the architecture before writing code
3. Write clean, well-structured, production-quality Python code
4. Include proper error handling and type hints
5. Add clear docstrings and comments
6. Test that imports and paths are correct
7. Reply in the same language the user uses.`,
            getAppendSystemPrompt: () => [],
            getPathMetadata: () => new Map(),
            extendResources: () => {},
            reload: async () => {},
        };

        emit({ type: "log", message: "Creating agent session..." });

        // Create session with coding tools
        const { session } = await createAgentSession({
            cwd,
            model,
            thinkingLevel: "off",
            authStorage,
            modelRegistry,
            resourceLoader,
            tools: createCodingTools(cwd),
            sessionManager: SessionManager.inMemory(),
            settingsManager: SettingsManager.inMemory({
                compaction: { enabled: false },
                retry: { enabled: true, maxRetries: 2 },
            }),
        });

        emit({ type: "log", message: "Agent session created, sending prompt..." });

        // Collect output & track files
        let fullOutput = "";
        const filesModified: string[] = [];

        session.subscribe((event: any) => {
            try {
                // Agent lifecycle events
                if (event.type === "turn_start") {
                    emit({ type: "log", message: "--- New turn ---" });
                }

                // Text streaming from assistant
                if (event.type === "message_update") {
                    const assistantEvent = event.assistantMessageEvent;
                    if (assistantEvent?.type === "text_delta") {
                        const delta = assistantEvent.delta;
                        fullOutput += delta;
                        emit({ type: "text_delta", delta });
                    }
                }

                // Tool execution lifecycle (SDK events)
                if (event.type === "tool_execution_start") {
                    const toolName = event.toolName || "unknown";
                    const args = event.args || {};
                    emit({ type: "tool_call", tool: toolName, input: args });
                }

                if (event.type === "tool_execution_end") {
                    const toolName = event.toolName || "unknown";
                    const result = event.result;
                    const isError = event.isError;

                    // Extract output text from result content
                    let outputText = "";
                    if (result?.content) {
                        for (const block of result.content) {
                            if (block.type === "text") {
                                outputText += block.text;
                            }
                        }
                    }
                    outputText = outputText.substring(0, 500);

                    emit({ type: "tool_result", tool: toolName, output: outputText, isError });

                    // Track file modifications
                    if (toolName === "write" || toolName === "edit") {
                        const args = event.args || {};
                        const filePath = args.file_path || args.path || args.file;
                        if (filePath && !filesModified.includes(filePath)) {
                            filesModified.push(filePath);
                            emit({ type: "file_modified", path: filePath });
                        }
                    }
                }

                // Turn end
                if (event.type === "turn_end") {
                    const toolResults = event.toolResults || [];
                    emit({ type: "log", message: `Turn ended (${toolResults.length} tool results)` });
                }
            } catch (e) {
                // Don't crash on event processing errors
                emit({ type: "log", message: `Event processing warning: ${e}` });
            }
        });

        // Run the prompt
        await session.prompt(prompt);

        emit({
            type: "done",
            output: fullOutput,
            files_modified: filesModified,
        });
    } catch (e: any) {
        emit({
            type: "error",
            error: e.message || String(e),
        });
        process.exit(1);
    }
}

main();
