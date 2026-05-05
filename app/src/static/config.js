window.APP_CONFIG = {
    // Fallback values when the frontend is served as plain static files.
    // When served from the FastAPI bridge container, /config.js is generated at runtime.
    BRIDGE_BASE_URL: "",
    PUBLIC_BRIDGE_URL: "",
    ANALYZE_VIA_BRIDGE: true,
    DIRECT_MODEL_ENABLED: false,
    TUNNEL_STATUS: "unknown",
    TUNNEL_ERROR: "",
    MODEL_API_CONFIGURED: false,
    ACTIVE_MODEL_API_URL: "",
    DEFAULT_MODEL_API_URL: "",
    DEFAULT_MODEL_API_KEY: "",
    SERVER_SIDE_MODEL_KEY_CONFIGURED: false,
    SERVER_SIDE_MODEL_KEY_MASKED: "",
    MODEL_SERVER_STATUS: "unknown",
    MODEL_SERVER_ERROR: "",
    MODEL_SERVER_PROVIDER: "",
    MODEL_SERVER_PUBLIC_URL: "",
    MODEL_SERVER_REMOTE_HOST: "",
    DEFAULT_VLM_MODE: "local",
    VLM_MODE_OPTIONS: ["local", "api", "disabled"],
    VLM_API_MODEL_OPTIONS: [
        "google/gemini-3.1-pro-preview",
        "google/gemini-2.5-pro",
        "x-ai/grok-4.20",
        "moonshotai/kimi-k2-thinking",
        "qwen/qwen2.5-vl-72b-instruct",
        "openai/gpt-4o"
    ]
};
