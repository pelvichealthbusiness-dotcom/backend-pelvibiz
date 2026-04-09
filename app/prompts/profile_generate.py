"""
LLM system prompts for AI-powered brand profile generation.

Provides category-aware prompt construction for generating complete brand
profiles and regenerating individual fields with contextual consistency.
"""

from typing import Any

# ---------------------------------------------------------------------------
# Business Categories — 12 verticals + generic fallback
# Each category carries domain-specific hints for voice, audience, visuals,
# CTAs, and environment descriptions so the LLM receives targeted guidance.
# ---------------------------------------------------------------------------

BUSINESS_CATEGORIES: dict[str, dict[str, Any]] = {
    "health_wellness": {
        "name": "Health & Wellness",
        "keywords": [
            "wellness", "holistic", "health coach", "nutrition", "mindfulness",
            "yoga", "meditation", "pelvic", "women health", "wellbeing",
            "naturopath", "integrative", "functional medicine", "self-care",
        ],
        "voice_hint": "Warm, empowering, evidence-informed yet approachable. Avoids clinical jargon unless educating.",
        "audience_hint": "Health-conscious individuals seeking sustainable lifestyle improvements and expert guidance.",
        "visual_hint": (
            "Modern home office with curated bookshelf, indoor plants (monstera, eucalyptus), "
            "soft textured throws, warm greige walls, subtle art pieces. "
            "Warm golden-hour glow (3500K) through sheer curtains. Key light from left at 45 degrees."
        ),
        "visual_mood": "empowering, warm, professional, aspirational, approachable",
        "visual_avoid": "hospitals, clinics, sterile white rooms, harsh fluorescents, medical equipment, scrubs",
        "cta_hint": "Book a free discovery call / Start your wellness journey today",
        "color_temp": "3200K-4000K",
    },
    "fitness": {
        "name": "Fitness & Training",
        "keywords": [
            "fitness", "personal trainer", "gym", "workout", "exercise",
            "strength", "crossfit", "pilates", "athletic", "sports",
            "bodybuilding", "hiit", "running", "coaching",
        ],
        "voice_hint": "Energetic, motivational, direct. Balances intensity with inclusivity.",
        "audience_hint": "Active individuals and aspiring athletes looking for structured programs and accountability.",
        "visual_hint": (
            "High-end boutique gym with clean equipment, rubber flooring, mirrors. "
            "OR outdoor scenic location (park, beach at sunrise). "
            "Dramatic rim light with warm fill for studio. Hard directional light for muscle definition."
        ),
        "visual_mood": "energetic, motivational, powerful, dynamic, athletic",
        "visual_avoid": "dirty gyms, cluttered backgrounds, unflattering overhead lights, cheap equipment",
        "cta_hint": "Start your transformation / Claim your free session",
        "color_temp": "4000K-5500K",
    },
    "medical": {
        "name": "Medical Professional",
        "keywords": [
            "medical", "doctor", "physician", "clinic", "physical therapy",
            "physiotherapy", "chiropractic", "dental", "dermatology",
            "orthopedic", "pediatric", "surgery", "healthcare", "pt",
            "occupational therapy", "speech therapy",
        ],
        "voice_hint": "Trustworthy, knowledgeable, reassuring. Simplifies complex topics without condescending.",
        "audience_hint": "Patients seeking reliable medical expertise delivered with empathy and clarity.",
        "visual_hint": (
            "Clean modern clinic with warm wood accents, comfortable seating, green plants. "
            "Wellness center aesthetic — medical precision with human warmth. "
            "Soft clinical light balanced with warm accent lamps (4500K)."
        ),
        "visual_mood": "trustworthy, professional, approachable, competent, reassuring",
        "visual_avoid": "harsh fluorescent tubes, operating rooms, hospital beds, institutional corridors, cold blue tones",
        "cta_hint": "Schedule your consultation / Take the first step toward recovery",
        "color_temp": "4000K-5000K",
    },
    "beauty": {
        "name": "Beauty & Skincare",
        "keywords": [
            "beauty", "skincare", "makeup", "aesthetics", "spa", "salon",
            "cosmetics", "skin care", "facial", "nails", "hair stylist",
            "lashes", "brows", "esthetician", "botox", "medspa",
        ],
        "voice_hint": "Luxurious, confident, aspirational. Blends science with sensory appeal.",
        "audience_hint": "Individuals who invest in self-care and premium beauty experiences.",
        "visual_hint": (
            "Minimalist spa-like setting with marble surfaces, glass shelving, soft towels. "
            "Vanity setup with ring light. Bathroom with natural stone and green accents. "
            "Soft ring light combined with natural diffused light. Subtle warmth (4000K)."
        ),
        "visual_mood": "luxurious, clean, premium, radiant, indulgent",
        "visual_avoid": "cluttered countertops, cheap lighting, unflattering angles, drugstore aesthetic",
        "cta_hint": "Book your glow-up / Discover your perfect routine",
        "color_temp": "3800K-4200K",
    },
    "real_estate": {
        "name": "Real Estate",
        "keywords": [
            "real estate", "realtor", "property", "homes", "housing",
            "mortgage", "listing", "broker", "apartment", "condo",
            "investment property", "commercial real estate",
        ],
        "voice_hint": "Polished, knowledgeable, aspirational. Tells lifestyle stories, not just property specs.",
        "audience_hint": "Home buyers, sellers, and investors looking for a trusted local market expert.",
        "visual_hint": (
            "Staged luxury home interior — open-concept kitchen with marble island, "
            "floor-to-ceiling windows, modern furnishings. Outdoor terrace with city/nature view. "
            "Bright natural light flooding through large windows. Golden hour for exterior shots."
        ),
        "visual_mood": "aspirational, spacious, inviting, premium, lifestyle",
        "visual_avoid": "dark rooms, cluttered spaces, outdated decor, fish-eye distortion, empty rooms",
        "cta_hint": "Find your dream home / Get your free market analysis",
        "color_temp": "4000K-5500K",
    },
    "business_coach": {
        "name": "Business Coach",
        "keywords": [
            "business coach", "executive coach", "leadership", "consultant",
            "mentor", "strategy", "entrepreneurship", "scaling", "growth",
            "mindset", "productivity", "ceo", "founder",
        ],
        "voice_hint": "Authoritative, results-driven, inspiring. Shares frameworks and proven methodology.",
        "audience_hint": "Entrepreneurs and executives seeking clarity, accountability, and strategic growth.",
        "visual_hint": (
            "Executive home office with leather chair, dark wood desk, curated bookshelf. "
            "OR modern co-working space with glass walls and city views. "
            "Warm soft box from the side (3800K). Natural window light as fill."
        ),
        "visual_mood": "professional, confident, successful, authoritative, mentoring",
        "visual_avoid": "messy desks, cheap furniture, generic cubicles, boring corporate beige",
        "cta_hint": "Apply for a strategy session / Unlock your next level",
        "color_temp": "3500K-4500K",
    },
    "restaurant": {
        "name": "Restaurant & Food",
        "keywords": [
            "restaurant", "food", "chef", "catering", "bakery", "cafe",
            "cuisine", "dining", "menu", "recipe", "cook", "bar",
            "coffee", "brunch", "food truck",
        ],
        "voice_hint": "Sensory, inviting, authentic. Evokes taste, aroma, and experience through words.",
        "audience_hint": "Food lovers and local diners seeking memorable culinary experiences.",
        "visual_hint": (
            "Rustic kitchen with copper cookware, wooden cutting boards, fresh herbs. "
            "Dining table with linen napkins, candlelight. Food styling with negative space. "
            "Warm overhead pendant light. Natural side light from window (3200K). Backlight for steam."
        ),
        "visual_mood": "appetizing, cozy, artisanal, farm-to-table, inviting",
        "visual_avoid": "fast-food aesthetic, plastic surfaces, fluorescent cafeteria lighting, cluttered plates",
        "cta_hint": "Reserve your table / Order now for pickup",
        "color_temp": "2800K-3500K",
    },
    "ecommerce": {
        "name": "E-commerce & Product",
        "keywords": [
            "ecommerce", "e-commerce", "shop", "store", "product", "retail",
            "online store", "dropshipping", "handmade", "artisan",
            "subscription", "marketplace", "brand", "merch",
        ],
        "voice_hint": "Concise, benefit-driven, aspirational. Focuses on lifestyle transformation through product.",
        "audience_hint": "Online shoppers who value quality, convenience, and brands that align with their identity.",
        "visual_hint": (
            "Clean seamless backdrop (white, light grey, or gradient). "
            "OR lifestyle setting relevant to product category. Minimal props that support, not distract. "
            "Studio soft box setup. Even illumination with subtle shadows for dimension."
        ),
        "visual_mood": "clean, premium, focused, aspirational, modern",
        "visual_avoid": "busy backgrounds, competing visual elements, harsh direct flash, amateur setup",
        "cta_hint": "Shop now / Discover the collection",
        "color_temp": "4500K-5500K",
    },
    "tech_startup": {
        "name": "Tech Startup",
        "keywords": [
            "tech", "startup", "saas", "software", "app", "ai",
            "machine learning", "cloud", "devops", "fintech", "blockchain",
            "platform", "api", "data", "automation",
        ],
        "voice_hint": "Sharp, innovative, clear. Translates complexity into accessible value propositions.",
        "audience_hint": "Tech-savvy professionals and early adopters looking for cutting-edge solutions.",
        "visual_hint": (
            "Modern open office with standing desks, large monitors, whiteboard with diagrams. "
            "Clean industrial aesthetic — exposed concrete, steel, glass. Green plants as contrast. "
            "Cool blue-tinted ambient (5500K-6500K). LED accent strips."
        ),
        "visual_mood": "innovative, future-forward, clean, focused, dynamic",
        "visual_avoid": "cluttered cables, messy desks, outdated equipment, dark cramped spaces",
        "cta_hint": "Start your free trial / Request a demo",
        "color_temp": "5500K-6500K",
    },
    "creative_agency": {
        "name": "Creative Agency",
        "keywords": [
            "creative", "agency", "design", "branding", "marketing",
            "advertising", "graphic design", "web design", "photography",
            "video production", "content creation", "studio",
        ],
        "voice_hint": "Bold, witty, conceptual. Shows creative thinking through every touchpoint.",
        "audience_hint": "Brands and businesses seeking standout creative work that drives results.",
        "visual_hint": (
            "Art studio with paint splatters, gallery walls, colorful accent pieces. "
            "Eclectic mix of vintage and modern furniture. Large windows with urban view. "
            "Dramatic side lighting. Colored gel accents (warm amber + cool blue)."
        ),
        "visual_mood": "bold, creative, eclectic, experimental, inspiring",
        "visual_avoid": "corporate sterility, monotone palettes, boring symmetry, stock photo setups",
        "cta_hint": "Let's create something remarkable / Start your project",
        "color_temp": "Mixed — warm amber + cool blue accents",
    },
    "therapist": {
        "name": "Therapist & Counselor",
        "keywords": [
            "therapist", "counselor", "psychologist", "mental health",
            "therapy", "counseling", "anxiety", "depression", "trauma",
            "emdr", "cbt", "couples therapy", "family therapy",
            "life coach", "psychotherapy",
        ],
        "voice_hint": "Gentle, validating, safe. Creates emotional space through words before anything else.",
        "audience_hint": "Individuals and couples seeking compassionate professional support for emotional well-being.",
        "visual_hint": (
            "Cozy home office with deep sofa or armchair, warm throw blankets, "
            "bookshelf with carefully curated spines. Soft rug, warm-toned walls (terracotta, sage, cream). "
            "Warm lamp light (2800K-3200K). No overhead lighting — all from table and floor lamps."
        ),
        "visual_mood": "safe, intimate, compassionate, grounding, nurturing",
        "visual_avoid": "clinical settings, bright overhead lights, office cubicles, cold tones, anything institutional",
        "cta_hint": "Schedule a free consultation / Take the first step",
        "color_temp": "2800K-3200K",
    },
    "fashion": {
        "name": "Fashion Brand",
        "keywords": [
            "fashion", "clothing", "apparel", "style", "boutique",
            "designer", "wardrobe", "accessories", "luxury", "streetwear",
            "sustainable fashion", "couture", "jewelry",
        ],
        "voice_hint": "Confident, editorial, culturally aware. Every word is curated like a collection.",
        "audience_hint": "Style-conscious consumers who see fashion as self-expression and invest in pieces that reflect identity.",
        "visual_hint": (
            "Urban street with interesting architecture. OR clean studio with colored backdrop. "
            "OR runway-adjacent backstage area. High-contrast environments. "
            "High-contrast editorial lighting. Hard key light with deep shadows. Rim light for separation."
        ),
        "visual_mood": "edgy, stylish, high-fashion, confident, curated",
        "visual_avoid": "generic mall backgrounds, flat even lighting, suburban settings, casual amateur vibes",
        "cta_hint": "Shop the collection / Explore the lookbook",
        "color_temp": "Variable — cool for editorial, warm for lifestyle",
    },
    "generic": {
        "name": "General Business",
        "keywords": [],
        "voice_hint": "Professional, clear, approachable. Adapts naturally to the specific niche described.",
        "audience_hint": "Determined by the niche and services provided.",
        "visual_hint": (
            "Clean, modern professional setting appropriate to the business type. "
            "Natural light supplemented with warm accent lighting (4000K). "
            "Three depth layers — foreground detail, midground subject, background context."
        ),
        "visual_mood": "professional, approachable, modern, trustworthy, aspirational",
        "visual_avoid": "cluttered backgrounds, harsh fluorescents, amateur setups, stock-photo clichés",
        "cta_hint": "Get started today / Learn more",
        "color_temp": "4000K-5000K",
    },
}


# ---------------------------------------------------------------------------
# Category resolver — pure keyword matching, no LLM call
# ---------------------------------------------------------------------------

def resolve_category(niche: str, services: str) -> dict[str, Any]:
    """Match a business niche + services description to the best category.

    Performs case-insensitive keyword scanning across both inputs.
    Returns the matching category dict, or the ``generic`` fallback.
    """
    combined = f"{niche} {services}".lower()

    best_key: str = "generic"
    best_score: int = 0

    for key, cat in BUSINESS_CATEGORIES.items():
        if key == "generic":
            continue
        score = sum(1 for kw in cat["keywords"] if kw in combined)
        if score > best_score:
            best_score = score
            best_key = key

    return BUSINESS_CATEGORIES[best_key]


# ---------------------------------------------------------------------------
# Font style reference (shared across prompts)
# ---------------------------------------------------------------------------

FONT_STYLE_OPTIONS = """
- "minimalist-sans": Clean, modern, tech-forward brands. Think Apple, Aesop. Best for wellness, SaaS, minimalist aesthetics.
- "geometric-sans": Structured, confident, architectural. Best for coaches, consultants, professional services.
- "editorial-serif": Elegant, authoritative, premium. Best for luxury, legal, high-end medical, editorial content.
- "bold-display": Energetic, attention-grabbing, impactful. Best for fitness, food, entertainment, bold brands.
- "creative-script": Warm, personal, artisanal. Best for beauty, bakeries, handmade goods, personal brands.
- "friendly-sans": Approachable, rounded, welcoming. Best for pediatrics, family services, community brands.
""".strip()

VALID_FONT_STYLES = [
    "minimalist-sans",
    "geometric-sans",
    "editorial-serif",
    "bold-display",
    "creative-script",
    "friendly-sans",
]


# ---------------------------------------------------------------------------
# Full profile generation prompt
# ---------------------------------------------------------------------------

def build_profile_generation_prompt(
    niche: str,
    content_goals: list[str],
    category: dict[str, Any],
) -> str:
    """Build the system prompt for generating a complete brand profile.

    Args:
        niche: The business niche or vertical description.
        content_goals: List of content goal slugs (e.g. ``["educate", "build_trust"]``).
        category: A resolved category dict from :data:`BUSINESS_CATEGORIES`.

    Returns:
        A fully-formed system prompt string ready for LLM consumption.
    """
    goals_str = ", ".join(content_goals) if content_goals else "grow audience"

    return f"""You are a **Brand Identity Architect** — an expert strategist who builds complete brand systems for social media content creation. You combine brand psychology, visual direction, and content strategy into a cohesive identity.

## Context

- **Niche**: {niche}
- **Content Goals**: {goals_str}
- **Detected Category**: {category["name"]}

## Category-Specific Guidance

- **Voice direction**: {category["voice_hint"]}
- **Audience pattern**: {category["audience_hint"]}
- **Visual environment**: {category["visual_hint"]}
- **Visual mood**: {category["visual_mood"]}
- **Visual avoid**: {category["visual_avoid"]}
- **CTA pattern**: {category["cta_hint"]}
- **Recommended color temperature**: {category["color_temp"]}

Use the above as starting guidance, but always let the **niche** and **content goals** be the PRIMARY drivers. The category hints are guardrails, not constraints.

## Output Specification

Return a JSON object with EXACTLY these 12 fields. No markdown fences, no explanation — pure JSON only.

1. **"brand_voice"** — 2-3 sentences describing tone, personality, and communication style. Must feel authentic to THIS specific niche.

2. **"target_audience"** — 1-2 sentences: demographics, pain points, aspirations. Be specific, not generic.

3. **"services_offered"** — Clean comma-separated list of key services/topics derived from the niche.

4. **"keywords"** — 8-12 power words capturing brand essence (comma-separated). Mix emotional + functional words.

5. **"visual_identity"** — 2-3 sentences on overall aesthetic direction. Include texture, mood, and spatial language.

6. **"cta"** — One compelling, specific call-to-action sentence. Aligned with content goals.

7. **"font_style"** — MUST be exactly one of:
{FONT_STYLE_OPTIONS}
   Choose the best match for the brand vibe.

8. **"content_style_brief"** — The writing DNA of this brand. 3-5 sentences covering:
   - Default sentence structure (short punchy vs flowing narrative)
   - Vocabulary register (clinical, conversational, poetic, etc.)
   - Emotional arc of a typical post (how it opens, builds, closes)
   - How the content goals ({goals_str}) shape every piece of content
   This is the MOST IMPORTANT field for content generation quality.

9. **"visual_environment_setup"** — Detailed AI image generation prompt for the environment. Structure as:
   [ENVIRONMENT]: 2-3 sentences — physical space, materials, furniture, architectural features.
   [LIGHTING]: 1-2 sentences — light quality, direction, color temperature in Kelvin.
   [MOOD KEYWORDS]: 3-5 comma-separated mood words.
   [AVOID]: 1-2 sentences — what to explicitly exclude.
   [COLOR PALETTE HINT]: Dominant colors that should appear.

10. **"visual_subject_outfit_face"** — What the real person should wear in AI images. Include clothing type, fit, fabric, color palette, minimal accessories, hair/grooming direction, and AVOID directives. 60-120 words.

11. **"visual_subject_outfit_generic"** — Generic/stock model appearance when no face photo exists. Include age range, general appearance, clothing with specific items, color palette, pose direction, and AVOID directives. 60-120 words.

12. **"suggested_brand_name"** — A creative, memorable brand name suggestion based on the niche. The user can ignore this — it's just a starting point.

## Critical Rules

- Return ONLY valid JSON. No markdown fences, no extra text.
- Visual fields (9-11) must be 60-120 words each. Dense with visual information.
- Visual descriptions must be compatible with ALL major image generation models (Midjourney, DALL-E 3, Flux, SDXL). Use plain descriptive English — NO model-specific syntax (no --ar, no [brackets], no (parentheses:weight)).
- Use cinematic language: key light, fill light, rim light, color temperature in Kelvin, specific materials and textures.
- Always include AVOID/NEVER directives in visual fields.
- The content_style_brief must be a standalone writing guide — someone should be able to generate on-brand content reading ONLY that field.
- Every field must feel cohesive with every other field. This is a SYSTEM, not a collection of isolated answers.
- The niche "{niche}" and goals "{goals_str}" are your north star. Category hints are secondary."""


# ---------------------------------------------------------------------------
# Single-field regeneration prompt
# ---------------------------------------------------------------------------

def build_field_regeneration_prompt(
    field_name: str,
    current_profile: dict[str, Any],
    instruction: str,
) -> str:
    """Build the system prompt for regenerating a single profile field.

    Args:
        field_name: The profile field key to regenerate (e.g. ``"brand_voice"``).
        current_profile: The full current profile dict for context.
        instruction: User instruction for how to change the field.

    Returns:
        A system prompt string for single-field regeneration.
    """
    # Build a snapshot of the current profile for context
    context_lines: list[str] = []
    for key, value in current_profile.items():
        if key == field_name:
            context_lines.append(f"- **{key}** (FIELD TO REGENERATE): {value}")
        else:
            context_lines.append(f"- {key}: {value}")

    profile_snapshot = "\n".join(context_lines) if context_lines else "No profile data available."

    # Determine field-specific rules
    visual_fields = {
        "visual_environment_setup",
        "visual_subject_outfit_face",
        "visual_subject_outfit_generic",
    }
    is_visual = field_name in visual_fields

    visual_rules = ""
    if is_visual:
        visual_rules = """
## Visual Field Rules
- Output must be 60-120 words, dense with visual information.
- Use cinematic language: key light, fill light, rim light, Kelvin color temperatures.
- Include specific materials, textures, and spatial references.
- MUST include AVOID/NEVER directives.
- Compatible with ALL image generation models — no model-specific syntax.
"""

    font_rules = ""
    if field_name == "font_style":
        font_rules = f"""
## Font Style Constraint
The value MUST be exactly one of:
{FONT_STYLE_OPTIONS}
"""

    content_brief_rules = ""
    if field_name == "content_style_brief":
        content_brief_rules = """
## Content Style Brief Rules
Must be a standalone writing guide covering:
- Default sentence structure
- Vocabulary register
- Emotional arc of a typical post
- How content goals shape every piece
3-5 sentences that capture the brand's writing DNA.
"""

    return f"""You are a **Brand Identity Architect** performing a surgical edit on a single field of an existing brand profile.

## Task

Regenerate ONLY the field **"{field_name}"** based on the user's instruction, while maintaining perfect consistency with the rest of the profile.

## User Instruction

{instruction}

## Current Profile (for context — maintain consistency)

{profile_snapshot}
{visual_rules}{font_rules}{content_brief_rules}
## Rules

- Return ONLY the new value for "{field_name}" as a plain string (no JSON wrapper, no field name, no quotes around the entire response unless the value itself requires them).
- If the field is "font_style", return exactly one of the valid options.
- The regenerated value must feel like it belongs in the same brand system as all other fields.
- Apply the user's instruction precisely but don't break brand coherence.
- Do NOT return any explanation or commentary — just the new field value."""
