import logging
from uuid import uuid4
from fastapi import APIRouter, Depends
from app.services.auth import get_current_user
from app.services.instagram_scraper import InstagramScraper
from app.services.style_analyzer import StyleAnalyzer
from app.services.brand import BrandService
from app.models.analyzer import AnalyzeRequest, AnalyzeResponse, ApplyStyleResponse
from app.dependencies import get_supabase_admin
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analyzer", tags=["analyzer"])


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_instagram(
    request: AnalyzeRequest,
    user: dict = Depends(get_current_user),
):
    """Scrape an Instagram account and analyze its style programmatically."""
    user_id = user["id"]
    scraper = InstagramScraper()
    analyzer = StyleAnalyzer()
    supabase = get_supabase_admin()

    # 1. Scrape profile + posts
    profile_data, posts = await scraper.scrape(request.username, request.max_posts, user_id=user_id)

    if not posts:
        from app.services.exceptions import AgentAPIError
        raise AgentAPIError(message=f"No posts found for @{request.username}", code="NO_POSTS", status_code=404)

    # 2. Analyze (pure Python, no AI)
    metrics = analyzer.analyze(posts, profile_data)

    # 3. Optional AI voice summary
    voice_summary = None
    if request.generate_voice_summary:
        try:
            from openai import AsyncOpenAI
            settings = get_settings()
            client = AsyncOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)

            captions_sample = [p["caption"][:200] for p in posts[:10] if p.get("caption")]
            prompt = f"""Based on these Instagram style metrics and caption samples, write a 150-word "Writing Voice DNA" profile in second person ("You write...").

Metrics:
- Hook types: {metrics.get('hook_types', {})}
- Caption avg length: {metrics.get('caption_avg_length', 0)} words
- CTA types: {metrics.get('cta_types', {})}
- Emoji frequency: {metrics.get('emoji_frequency', 0)} per post
- Content categories: {metrics.get('content_categories', {})}
- Top keywords: {[k['word'] for k in metrics.get('top_keywords', [])[:10]]}

Sample captions (first lines):
{chr(10).join(c.split(chr(10))[0] for c in captions_sample[:5])}

Write a concise, actionable voice profile."""

            response = await client.chat.completions.create(
                model=settings.llm_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
                max_tokens=300,
                timeout=15,
            )
            voice_summary = response.choices[0].message.content
        except Exception as e:
            logger.warning(f"Voice summary generation failed: {e}")

    # 4. Map metrics to frontend-expected format
    hook_types = metrics.get('hook_types', {})
    top_hook = max(hook_types, key=hook_types.get) if hook_types else 'mixed'
    cta_types = metrics.get('cta_types', {})
    top_cta = max(cta_types, key=cta_types.get) if cta_types else 'none'
    frontend_metrics = {
        'avg_caption_length': int(metrics.get('caption_avg_length', 0)),
        'tone': 'Direct and engaging' if metrics.get('hook_second_person_rate', 0) > 0.3 else 'Informative',
        'hook_style': f'{top_hook} ({int(hook_types.get(top_hook, 0)*100)}%)' if hook_types else 'mixed',
        'cta_pattern': top_cta.replace('_', ' ').title() if cta_types else 'None detected',
        'emoji_usage': f'{metrics.get("emoji_frequency", 0):.1f} per post' if metrics.get('emoji_frequency', 0) > 0 else 'Minimal',
        'hashtag_avg': metrics.get('hashtag_avg_count', 0),
        'recurring_topics': [k['word'] for k in metrics.get('top_keywords', [])[:8]],
        'unique_phrases': [],
        'content_types': metrics.get('content_categories', {}),
        'follower_count': profile_data.get('followers', 0),
        'full_name': profile_data.get('full_name', ''),
        'profile_pic_url': profile_data.get('profile_pic_url', ''),
    }

    # 5. Save to social_scrapes
    scrape_id = str(uuid4())
    try:
        supabase.table("social_scrapes").insert({
            "id": scrape_id,
            "user_id": user_id,
            "username": request.username,
            "platform": "instagram",
            "raw_posts": {"profile": profile_data, "posts_count": len(posts)},
            "style_metrics": metrics,
            "metrics": frontend_metrics,
            "style_brief": voice_summary or "",
            "post_count": len(posts),
        }).execute()
    except Exception as e:
        logger.error(f"Failed to save scrape: {e}")

    return AnalyzeResponse(
        scrape_id=scrape_id,
        username=request.username,
        post_count=len(posts),
        followers=profile_data.get("followers", 0),
        metrics=metrics,
        voice_summary=voice_summary,
    )


@router.get("/results/{scrape_id}")
async def get_results(
    scrape_id: str,
    user: dict = Depends(get_current_user),
):
    """Get stored analysis results."""
    supabase = get_supabase_admin()
    result = supabase.table("social_scrapes").select("*").eq("id", scrape_id).eq("user_id", user["id"]).maybe_single().execute()
    if not result.data:
        from app.services.exceptions import AgentAPIError
        raise AgentAPIError(message="Analysis not found", code="NOT_FOUND", status_code=404)
    return result.data


@router.post("/apply/{scrape_id}", response_model=ApplyStyleResponse)
async def apply_style(
    scrape_id: str,
    user: dict = Depends(get_current_user),
):
    """Apply analyzed style to user's brand profile."""
    user_id = user["id"]
    supabase = get_supabase_admin()

    scrape = supabase.table("social_scrapes").select("*").eq("id", scrape_id).eq("user_id", user_id).maybe_single().execute()
    if not scrape.data:
        from app.services.exceptions import AgentAPIError
        raise AgentAPIError(message="Analysis not found", code="NOT_FOUND", status_code=404)

    voice = scrape.data.get("style_brief", "")
    metrics = scrape.data.get("style_metrics", {})

    style_brief = voice
    if metrics:
        hook_info = metrics.get("hook_types", {})
        cta_info = metrics.get("cta_types", {})
        if hook_info:
            top_hook = max(hook_info, key=hook_info.get) if hook_info else "mixed"
            style_brief += f"\nPrimary hook style: {top_hook} ({int(hook_info.get(top_hook, 0)*100)}% of posts)."
        if cta_info:
            top_cta = max(cta_info, key=cta_info.get) if cta_info else "mixed"
            style_brief += f"\nPreferred CTA: {top_cta}."
        if metrics.get("caption_avg_length"):
            style_brief += f"\nTarget caption length: ~{int(metrics['caption_avg_length'])} words."
        if metrics.get("hashtag_avg_count"):
            style_brief += f"\nHashtags per post: ~{int(metrics['hashtag_avg_count'])}."

    brand_service = BrandService()
    supabase.table("profiles").update({
        "content_style_brief": style_brief.strip(),
    }).eq("id", user_id).execute()
    brand_service.invalidate_cache(user_id)

    return ApplyStyleResponse(
        applied=True,
        content_style_brief=style_brief.strip(),
        source_username=scrape.data.get("username", ""),
    )
