import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from app.services.auth import get_current_user
from app.services.instagram_scraper import InstagramScraper
from app.services.style_analyzer import StyleAnalyzer
from app.services.brand import BrandService
from app.services.content_intelligence import ContentIntelligenceService
from app.models.analyzer import AnalyzeRequest, AnalyzeResponse, ApplyStyleResponse
from app.dependencies import get_supabase_admin
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analyzer", tags=["analyzer"])


def _timestamp_to_iso(timestamp: int | float | None) -> str | None:
    if not timestamp:
        return None
    try:
        return datetime.fromtimestamp(float(timestamp), tz=timezone.utc).isoformat()
    except Exception:
        return None


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_instagram(
    request: AnalyzeRequest,
    user: dict = Depends(get_current_user),
):
    """Scrape an Instagram account and analyze its style programmatically."""
    user_id = user["id"]
    scraper = InstagramScraper()
    analyzer = StyleAnalyzer()
    content_service = ContentIntelligenceService()

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

    # 5. Save normalized content into the new pipeline
    saved = await content_service.store_scrape(
        user_id=user_id,
        handle=request.username,
        account_type='competitor',
        display_name=profile_data.get('full_name', ''),
        metadata={
            'followers': profile_data.get('followers', 0),
            'following': profile_data.get('following', 0),
            'is_verified': profile_data.get('is_verified', False),
        },
        posts=[
            {
                'id': post.get('id', ''),
                'caption': post.get('caption', ''),
                'posted_at': _timestamp_to_iso(post.get('timestamp')),
                'media_type': 'reel' if post.get('media_type') == 2 else 'carousel' if post.get('is_carousel') else 'post',
                'likes': post.get('likes', 0),
                'comments': post.get('comments', 0),
                'raw_data': post,
                'analysis_status': 'pending',
            }
            for post in posts
            if post.get('id')
        ],
    )

    account = saved.get('account', {})
    scrape_id = account.get('id', '')

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
    """Get stored analysis results from the content-intelligence pipeline."""
    service = ContentIntelligenceService()
    result = await service.generate_brief(user_id=user["id"], account_id=scrape_id)
    if not result.get('ready'):
        from app.services.exceptions import AgentAPIError
        raise AgentAPIError(message="Analysis not found", code="NOT_FOUND", status_code=404)
    return result


@router.post("/apply/{scrape_id}", response_model=ApplyStyleResponse)
async def apply_style(
    scrape_id: str,
    user: dict = Depends(get_current_user),
):
    """Apply the generated content brief to user's brand profile."""
    user_id = user["id"]
    supabase = get_supabase_admin()

    service = ContentIntelligenceService(supabase)
    result = await service.generate_brief(user_id=user_id, account_id=scrape_id)
    if not result.get('ready'):
        from app.services.exceptions import AgentAPIError
        raise AgentAPIError(message="Analysis not found", code="NOT_FOUND", status_code=404)

    style_brief = result.get('brief_markdown', '')
    account = supabase.table("content_accounts").select("handle").eq("id", scrape_id).eq("user_id", user_id).maybe_single().execute()
    source_username = account.data.get("handle", "") if account.data else ""

    brand_service = BrandService()
    supabase.table("profiles").update({
        "content_style_brief": style_brief.strip(),
    }).eq("id", user_id).execute()
    brand_service.invalidate_cache(user_id)

    return ApplyStyleResponse(
        applied=True,
        content_style_brief=style_brief.strip(),
        source_username=source_username,
    )


@router.get("/brief")
async def content_brief(
    account_id: str | None = None,
    user: dict = Depends(get_current_user),
):
    """Generate a performance brief from the content intelligence pipeline."""
    service = ContentIntelligenceService()
    return await service.generate_brief(user_id=user["id"], account_id=account_id)
