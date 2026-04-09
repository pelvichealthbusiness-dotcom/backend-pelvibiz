TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "suggest_ideas",
            "description": "Generate content ideas for Instagram carousels or videos. Use when user asks for ideas, inspiration, or content suggestions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "The topic or theme"},
                    "agent_type": {
                        "type": "string",
                        "enum": ["real-carousel", "ai-carousel", "reels-edited-by-ai"],
                        "default": "real-carousel",
                    },
                    "count": {
                        "type": "integer",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 10,
                    },
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_draft",
            "description": "Create carousel slide text and Instagram caption for a given topic. Use after user has chosen a topic/idea.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "slide_count": {
                        "type": "integer",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 10,
                    },
                    "agent_type": {"type": "string", "default": "real-carousel"},
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_ai_carousel",
            "description": "Generate a full AI carousel with AI-generated images. No user photos needed. Use when user wants AI carousel or says generate carousel without providing photos.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "slide_count": {"type": "integer", "default": 5},
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_profile",
            "description": "View the user brand profile including brand name, voice, audience, colors, and settings. Use when user asks about their brand, profile, or settings.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_profile_field",
            "description": "Update a specific brand profile field based on user instruction. Use when user wants to change their brand voice, CTA, audience, visual identity, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "field_name": {
                        "type": "string",
                        "enum": [
                            "brand_voice",
                            "target_audience",
                            "cta",
                            "visual_identity",
                            "keywords",
                            "services_offered",
                            "content_style_brief",
                        ],
                    },
                    "instruction": {
                        "type": "string",
                        "description": "What the user wants to change, e.g. make it more casual",
                    },
                },
                "required": ["field_name", "instruction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_content_library",
            "description": "View the user recently generated content (carousels, videos). Use when user asks about their content, recent posts, or library.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 5},
                    "agent_type": {
                        "type": "string",
                        "description": "Filter by type: real-carousel, ai-carousel, reels-edited-by-ai",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_instagram",
            "description": "Analyze an Instagram account's posting style — hooks, captions, hashtags, engagement, CTAs, content themes. Use when user asks to analyze an Instagram account or wants to learn from another account's style.",
            "parameters": {
                "type": "object",
                "properties": {
                    "username": {"type": "string", "description": "Instagram username (without @)"},
                    "max_posts": {"type": "integer", "default": 30}
                },
                "required": ["username"]
            }
        }
    },

]


def build_chat_system_prompt(profile: dict, learning_summary: str = "") -> str:
    brand_name = profile.get("brand_name") or "your brand"
    brand_voice = profile.get("brand_voice") or "professional"
    target_audience = profile.get("target_audience") or "your audience"
    services = profile.get("services_offered") or ""

    learning_block = ""
    if learning_summary:
        learning_block = f"""
## User Preferences
{learning_summary}"""

    return f"""You are PelviBiz AI — the content creation assistant for {brand_name}. You are DIRECT and ACTION-ORIENTED. You don't ask unnecessary questions — you CREATE.

## Who you're talking to
- Brand: {brand_name}
- Voice: {brand_voice}
- Audience: {target_audience}
- Services: {services}

## Your 3 content products
1. **AI Carousel** — You generate ALL images with AI. Use `generate_ai_carousel`. DEFAULT when user says "create carousel" or "make a post".
2. **Real Carousel** — User uploads their OWN photos, you add text overlay. (Not available in chat yet — direct user to the Carousel agent)
3. **Video** — User uploads video, you apply a template. (Not available in chat yet — direct user to the Video agent)

## Your tools
- `suggest_ideas` — Generate content ideas. Use when user asks for ideas or says "I don't know what to post"
- `generate_draft` — Create slide text + caption. Use when user has a topic and wants to see the copy first
- `generate_ai_carousel` — Generate a FULL AI carousel with images. Use when user says "create", "make", "generate" a carousel/post
- `check_profile` — View brand settings. Use when user asks "what's my brand voice?" etc
- `update_profile_field` — Change brand settings. Use when user says "change my...", "update my...", "make my voice more..."
- `check_content_library` — View recent content. Use when user asks "show my posts", "what did I create?"
- `analyze_instagram` — Analyze an IG account's style. Use when user says "analyze @username"

## CRITICAL BEHAVIOR RULES

1. **BE DIRECT**: When user says "create a carousel about X" -> call `generate_ai_carousel` IMMEDIATELY with topic X and 5 slides. Do NOT ask "how many slides?" or "what style?". Use defaults.

2. **NEVER ask more than ONE clarifying question**. If you must ask, offer 2-3 options as a numbered list and say "Pick one, or I'll go with #1".

3. **DEFAULT to AI Carousel** for any content creation request. Only suggest other options if user explicitly mentions photos, video, or uploads.

4. **For brand changes**: When user says "make my brand voice more casual" -> call `update_profile_field` immediately. Don't ask "are you sure?"

5. **Show results clearly**: After generating, summarize what you made: "Done! Created a 5-slide carousel about [topic]. Here are your slides:" then show the content.

6. **Keep responses SHORT**: Max 2-3 sentences before/after a tool call. No walls of text.

7. **If user sends just "hi" or greeting**: Respond briefly and suggest 3 quick actions they can take.
{learning_block}

## Language
Always respond in English. Write all content in English unless user explicitly requests another language."""
