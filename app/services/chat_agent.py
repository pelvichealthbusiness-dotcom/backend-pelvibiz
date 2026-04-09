import json
import logging
import base64
from uuid import uuid4

from openai import AsyncOpenAI

from app.config import get_settings
from app.dependencies import get_supabase_admin
from app.services.brand import BrandService
from app.services.instagram_scraper import InstagramScraper
from app.services.style_analyzer import StyleAnalyzer
from app.services.learning import LearningService
from app.services.ideas_engine import IdeasEngine
from app.services.draft_engine import DraftEngine
from app.services.content_strategy import ContentStrategyService
from app.services.image_generator import ImageGeneratorService
from app.services.storage import StorageService
from app.services.watermark import WatermarkService
from app.services.credits import CreditsService
from app.services.profile_engine import ProfileEngine
from app.prompts.chat_system import build_chat_system_prompt, TOOL_DEFINITIONS

logger = logging.getLogger(__name__)


class ChatAgent:
    """Orchestrates conversational AI with tool execution.

    Single entry point for all chat interactions. Composes existing
    services behind an LLM with function-calling.
    """

    def __init__(self):
        settings = get_settings()
        self.client = AsyncOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
        )
        self.model = settings.llm_model
        self.supabase = get_supabase_admin()

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def chat(
        self,
        user_id: str,
        message: str,
        conversation_id: str | None = None,
    ) -> dict:
        """Process a user message and return the assistant response."""

        # 1. Load brand profile + learning patterns
        brand_service = BrandService()
        learning_service = LearningService()

        profile = await brand_service.load_profile(user_id)
        patterns = await learning_service.get_patterns(user_id)
        learning_summary = (
            patterns.get("learning_summary", "") if patterns else ""
        )

        # 2. Get or create conversation
        if not conversation_id:
            conversation_id = str(uuid4())
            try:
                self.supabase.table("conversations").insert(
                    {
                        "id": conversation_id,
                        "user_id": user_id,
                        "agent_type": "pelvibiz-ai",
                        "title": message[:100],
                    }
                ).execute()
            except Exception as exc:
                logger.warning(f"Failed to create conversation: {exc}")

        # 3. Load conversation history (last 20 messages)
        history = self._load_history(user_id, conversation_id)

        # 4. Build messages array
        system_prompt = build_chat_system_prompt(profile, learning_summary)
        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": message})

        # 5. First LLM call (may include tool_calls)
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=TOOL_DEFINITIONS,
                temperature=0.6,
                max_tokens=4096,
                timeout=30,
            )
        except Exception as exc:
            logger.error(f"LLM call failed: {exc}")
            return self._build_response(
                "Sorry, I am having trouble right now. Please try again.",
                conversation_id,
                [],
                [],
            )

        choice = response.choices[0]
        tool_calls_results: list[dict] = []
        media_urls: list[str] = []

        # 6. If the LLM wants to call tools, execute them
        if choice.message.tool_calls:
            tool_messages: list = [choice.message]

            for tc in choice.message.tool_calls:
                tool_name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}

                logger.info(f"Executing tool: {tool_name} args={args}")
                result = await self._execute_tool(tool_name, args, user_id)
                tool_calls_results.append(
                    {
                        "tool_name": tool_name,
                        "result": result,
                        "success": "error" not in result,
                    }
                )

                if "media_urls" in result:
                    media_urls.extend(result["media_urls"])

                tool_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, default=str),
                    }
                )

            # 7. Second LLM call -- interpret tool results
            try:
                final_response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages + tool_messages,
                    temperature=0.6,
                    max_tokens=2000,
                    timeout=30,
                )
                assistant_message = (
                    final_response.choices[0].message.content or "Done!"
                )
            except Exception as exc:
                logger.error(f"Final LLM call failed: {exc}")
                assistant_message = (
                    "I executed the action but could not generate a summary. "
                    "Check the results above."
                )
        else:
            assistant_message = choice.message.content or "I am here to help!"

        # 8. Persist messages
        self._save_message(user_id, conversation_id, "user", message)
        self._save_message(
            user_id,
            conversation_id,
            "assistant",
            assistant_message,
            metadata={
                "tool_calls": tool_calls_results,
                "media_urls": media_urls,
            },
        )

        return self._build_response(
            assistant_message, conversation_id, tool_calls_results, media_urls
        )

    # ------------------------------------------------------------------
    # History helpers
    # ------------------------------------------------------------------

    def _load_history(
        self, user_id: str, conversation_id: str
    ) -> list[dict]:
        try:
            result = (
                self.supabase.table("messages")
                .select("role, content")
                .eq("user_id", user_id)
                .eq("conversation_id", conversation_id)
                .order("created_at", desc=False)
                .limit(20)
                .execute()
            )
            return [
                {"role": m["role"], "content": m["content"]}
                for m in (result.data or [])
            ]
        except Exception:
            return []

    def _save_message(
        self,
        user_id: str,
        conversation_id: str,
        role: str,
        content: str,
        metadata: dict | None = None,
    ):
        try:
            self.supabase.table("messages").insert(
                {
                    "id": str(uuid4()),
                    "user_id": user_id,
                    "agent_type": "pelvibiz-ai",
                    "role": role,
                    "content": content,
                    "conversation_id": conversation_id,
                    "metadata": metadata or {},
                }
            ).execute()
        except Exception as exc:
            logger.error(f"Failed to save message: {exc}")

    # ------------------------------------------------------------------
    # Tool execution dispatcher
    # ------------------------------------------------------------------

    async def _execute_tool(
        self, tool_name: str, args: dict, user_id: str
    ) -> dict:
        try:
            if tool_name == "suggest_ideas":
                return await self._tool_suggest_ideas(args, user_id)
            elif tool_name == "generate_draft":
                return await self._tool_generate_draft(args, user_id)
            elif tool_name == "generate_ai_carousel":
                return await self._tool_generate_ai_carousel(args, user_id)
            elif tool_name == "check_profile":
                return await self._tool_check_profile(user_id)
            elif tool_name == "update_profile_field":
                return await self._tool_update_profile_field(args, user_id)
            elif tool_name == "check_content_library":
                return await self._tool_check_content_library(args, user_id)
            elif tool_name == "analyze_instagram":
                return await self._tool_analyze_instagram(args, user_id)
            else:
                return {"error": f"Unknown tool: {tool_name}"}
        except Exception as exc:
            logger.error(f"Tool {tool_name} failed: {exc}")
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Individual tool executors
    # ------------------------------------------------------------------

    async def _tool_suggest_ideas(self, args: dict, user_id: str) -> dict:
        engine = IdeasEngine()
        result = await engine.generate_ideas(
            user_id=user_id,
            message=args.get("topic", ""),
            agent_type=args.get("agent_type", "real-carousel"),
            count=args.get("count", 5),
        )
        return {
            "ideas": result.get("ideas", []),
            "reasoning": result.get("reasoning", ""),
        }

    async def _tool_generate_draft(self, args: dict, user_id: str) -> dict:
        engine = DraftEngine()
        result = await engine.generate_draft(
            user_id=user_id,
            topic=args.get("topic", ""),
            slide_count=args.get("slide_count", 5),
        )
        return result

    async def _tool_generate_ai_carousel(
        self, args: dict, user_id: str
    ) -> dict:
        from app.prompts.ai_carousel_generate import (
            build_generic_slide_prompt,
            build_card_slide_prompt,
        )
        from app.models.ai_carousel import SlideType
        from app.utils.image import force_resolution

        # Check credits first
        credits = CreditsService()
        await credits.check_credits(user_id)

        brand = BrandService()
        profile = await brand.load_profile(user_id)

        strategy = ContentStrategyService()
        plan = await strategy.plan_ai(
            args.get("topic", ""), profile, args.get("slide_count", 5)
        )

        img_gen = ImageGeneratorService()
        storage = StorageService()
        watermark = WatermarkService()
        media_urls: list[str] = []

        for slide in plan.slides:
            try:
                if slide.slide_type == SlideType.GENERIC:
                    prompt = build_generic_slide_prompt(
                        visual_prompt=slide.visual_prompt,
                        text=slide.text,
                        text_position=slide.text_position,
                        font_prompt=profile.get("font_prompt", "Sans-serif"),
                        font_style=profile.get("font_style", "bold"),
                        font_size=profile.get("font_size", "38px"),
                        color_primary=profile.get(
                            "brand_color_primary", "#000"
                        ),
                        color_secondary=profile.get(
                            "brand_color_secondary", "#FFF"
                        ),
                    )
                else:
                    prompt = build_card_slide_prompt(
                        text=slide.text,
                        text_position=slide.text_position or "Center",
                        font_prompt=profile.get("font_prompt", "Sans-serif"),
                        font_style=profile.get("font_style", "bold"),
                        font_size=profile.get("font_size", "42px"),
                        color_primary=profile.get(
                            "brand_color_primary", "#000"
                        ),
                        color_secondary=profile.get(
                            "brand_color_secondary", "#FFF"
                        ),
                    )

                gen_b64 = await img_gen.generate_from_prompt(prompt)
                img_bytes = force_resolution(base64.b64decode(gen_b64))
                img_bytes = await watermark.apply(
                    img_bytes, profile.get("logo_url"), user_id
                )
                url = await storage.upload_image(
                    base64.b64encode(img_bytes).decode(), user_id
                )
                media_urls.append(url)
            except Exception as exc:
                logger.error(f"Chat AI carousel slide failed: {exc}")

        # Save to requests_log
        msg_id = str(uuid4())
        try:
            self.supabase.table("requests_log").upsert(
                {
                    "id": msg_id,
                    "user_id": user_id,
                    "agent_type": "ai-carousel",
                    "title": args.get("topic", "AI Carousel"),
                    "reply": plan.reply,
                    "caption": plan.caption,
                    "media_urls": media_urls,
                    "published": False,
                },
                on_conflict="id",
            ).execute()
        except Exception:
            pass

        # Increment credits
        try:
            await credits.increment_credits(user_id)
        except Exception:
            pass

        return {
            "media_urls": media_urls,
            "caption": plan.caption,
            "reply": plan.reply,
            "slides": len(media_urls),
        }

    async def _tool_check_profile(self, user_id: str) -> dict:
        brand = BrandService()
        profile = await brand.load_profile(user_id)
        return {
            "brand_name": profile.get("brand_name"),
            "brand_voice": profile.get("brand_voice"),
            "target_audience": profile.get("target_audience"),
            "services_offered": profile.get("services_offered"),
            "cta": profile.get("cta"),
            "credits_used": profile.get("credits_used"),
            "credits_limit": profile.get("credits_limit"),
        }

    async def _tool_update_profile_field(
        self, args: dict, user_id: str
    ) -> dict:
        engine = ProfileEngine()
        brand = BrandService()
        profile = await brand.load_profile(user_id)
        result = await engine.regenerate_field(
            field_name=args.get("field_name", ""),
            current_profile=profile,
            instruction=args.get("instruction", ""),
        )
        # Auto-save the updated field
        self.supabase.table("profiles").update(
            {args["field_name"]: result["new_value"]}
        ).eq("id", user_id).execute()
        brand.invalidate_cache(user_id)
        return result

    async def _tool_check_content_library(
        self, args: dict, user_id: str
    ) -> dict:
        limit = args.get("limit", 5)
        query = (
            self.supabase.table("requests_log")
            .select(
                "id, agent_type, title, caption, media_urls, published, created_at"
            )
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
        )

        if args.get("agent_type"):
            query = query.eq("agent_type", args["agent_type"])

        result = query.execute()
        items = []
        for r in result.data or []:
            items.append(
                {
                    "id": r["id"],
                    "type": r["agent_type"],
                    "title": r["title"],
                    "media_count": len(r.get("media_urls") or []),
                    "published": r.get("published", False),
                    "created_at": str(r["created_at"]),
                }
            )
        return {"items": items, "total": len(items)}

    async def _tool_analyze_instagram(self, args: dict, user_id: str) -> dict:
        scraper = InstagramScraper()
        analyzer_svc = StyleAnalyzer()
        profile_data, posts = await scraper.scrape(
            args.get("username", ""), args.get("max_posts", 30)
        )
        if not posts:
            return {"error": f"No posts found for @{args.get('username')}"}
        metrics = analyzer_svc.analyze(posts, profile_data)
        return {
            "username": args.get("username"),
            "followers": profile_data.get("followers", 0),
            "post_count": len(posts),
            "hook_types": metrics.get("hook_types", {}),
            "content_categories": metrics.get("content_categories", {}),
            "caption_avg_length": metrics.get("caption_avg_length", 0),
            "hashtag_avg_count": metrics.get("hashtag_avg_count", 0),
            "engagement_rate": metrics.get("engagement_rate", 0),
            "cta_types": metrics.get("cta_types", {}),
            "top_keywords": [k["word"] for k in metrics.get("top_keywords", [])[:10]],
            "emoji_frequency": metrics.get("emoji_frequency", 0),
            "posts_per_week": metrics.get("posts_per_week", 0),
        }

    # ------------------------------------------------------------------
    # Response builder
    # ------------------------------------------------------------------

    def _build_response(
        self,
        message: str,
        conversation_id: str,
        tool_calls: list,
        media_urls: list,
    ) -> dict:
        return {
            "message": message,
            "conversation_id": conversation_id,
            "message_id": str(uuid4()),
            "tool_calls": tool_calls,
            "media_urls": media_urls,
            "metadata": {},
        }
