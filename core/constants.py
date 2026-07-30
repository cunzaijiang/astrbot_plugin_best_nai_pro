"""
插件常量与预设。
"""

from typing import Dict, List

LOG_TAG = "[魔法绘图]"
PLUGIN_NAME = "astrbot_plugin_best_nai_pro"
PAGE_API_PREFIX = f"/{PLUGIN_NAME}/studio"
PROXY_HOST = "127.0.0.1"
PROXY_PORT = 8969
IMAGE_GEN_BASE_URL_DEFAULT = ""

# 自然语言 → SD/NAI 标签
TRANSLATE_SYSTEM_PROMPT = (
    "You translate natural-language descriptions into compact, comma-separated "
    "Stable Diffusion / NovelAI prompt tags. Output ONLY the tags — no "
    "explanations, no markdown, no thinking block, no labels, no preamble.\n"
    "\n"
    "Output format (strict):\n"
    "  - Single line, English, lowercase, tags separated by ', '.\n"
    "  - Each tag = 1-3 words. Noun/adjective form. No articles, no verbs, "
    "no full sentences.\n"
    "  - Tag cap: 25-40 total. Stop once the input is covered; do not pad.\n"
    "\n"
    "Output order (mandatory):\n"
    "  1) Subject tags (1-8): who/what is in the image, anatomy, identity.\n"
    "  2) Action/scene tags (1-8): pose, location, props, lighting, atmosphere.\n"
    "  3) Style tags (0-4): medium, art style, mood.\n"
    "\n"
    "NAI weighting (apply to 3-5 key tags, prefer subject identity & key props):\n"
    "  - 1.2::keyword::  emphasizes; 1.5::keyword::  strong emphasis.\n"
    "  - -1::keyword::  or 0.5::keyword::  suppresses.\n"
    "  - {{keyword}}   ≈ 1.05× boost.\n"
    "\n"
    "STRICT RULES — never violate:\n"
    "  - Do NOT add quality tags (masterpiece, best quality, absurdres, "
    "highly detailed, etc.). Quality and artist tags are injected separately "
    "via an artist/preset parameter; re-adding them here causes duplication "
    "and weight conflicts.\n"
    "  - Do NOT invent visual details not in the input — no inferring "
    "makeup, lighting direction, weather, time-of-day, indoor/outdoor, or "
    "accessories that are not explicitly mentioned. If a concept is "
    "implied by a named object (e.g. 'umbrella' implies 'rainy'), that "
    "counts as in the input; do not extend further.\n"
    "  - Do NOT add aspect-ratio, framing-shape, or size tags — even if "
    "the input mentions 1:1, 方形, square, 横图, portrait, landscape, etc. "
    "These are handled by a separate size parameter; mention them only as "
    "a passive composition tag (e.g. 'half body', 'upper body') never as "
    "an aspect.\n"
    "  - Do NOT add negative-prompt tags like 'no text, no watermark, "
    "no logo' (handled via negative prompt).\n"
    "  - Do NOT output multiple synonymous tags — pick ONE concise "
    "descriptor per concept (e.g. 'urban style' alone, not 'urban style, "
    "contemporary style, stylish ensemble'). Same applies to atmosphere "
    "tags and quality concepts.\n"
    "  - Do NOT translate character names or transliterate; keep canonical "
    "form (e.g. 'muelsyse(Arknights)' if it appears in input, stays as-is).\n"
    "\n"
    "Examples (note: NO quality tags, weighted syntax on key descriptors):\n"
    "\n"
    "Input: 孤独的少女站在月光下的废墟里，穿着黑色连衣裙\n"
    "Output: 1girl, solo, 1.2::black dress::, standing, ruins, 1.3::moonlight::, night, dramatic lighting, full body\n"
    "\n"
    "Input: 一个开朗的动漫男孩拿武士刀，日落海滩，动态姿势\n"
    "Output: 1boy, 1.1::katana::, happy expression, beach, 1.3::sunset::, 1.2::dynamic pose::, ocean waves, wind, full body\n"
    "\n"
    "Input: modern living room, a cat sleeping on sofa, oil painting style\n"
    "Output: indoor, modern living room, cat, sleeping, sofa, oil painting, soft lighting, cozy atmosphere, 0.5::cluttered::, 1.2::oil painting style::\n"
    "\n"
    "Input: 镜前自拍穿搭，银色长发，戴墨镜\n"
    "Output: 1girl, mirror selfie, half body, looking at viewer, modern fashion, 1.1::sunglasses::, 0.8::casual outfit::, indoor, soft lighting"
)

IMAGE_STYLES: Dict[str, str] = {
    "vertical": "条漫清新风",
    "comicDoujin": "同人分镜风",
    "r18": "半立体唯美风",
    "lolita25d": "半立体幼态风",
    "anime": "里番本格风",
    "galgame": "视觉小说风",
    "custom": "自定义",
}

IMAGE_SIZES: Dict[str, List[int]] = {
    "竖图": [832, 1216],
    "横图": [1216, 832],
    "方图": [1024, 1024],
    "portrait": [832, 1216],
    "landscape": [1216, 832],
    "square": [1024, 1024],
}

DEFAULT_ARTISTS: Dict[str, str] = {
    "vertical": (
        "masterpiece, best quality,[[[artist:dishwasher1910]]], "
        "{{yd_(orange_maru)}}, [artist:ciloranko], [artist:sho_(sho_lwlw)], "
        "[ningen mame], soft lighting,year 2024"
    ),
    "comicDoujin": (
        "masterpiece,best quality,ultra detailed,by oda takeo,by uchiokazumasa,"
        "by azule,TV anime screencap,clean cel shading,soft lineart,subtle bloom glow"
    ),
    "r18": (
        "20::best quality, absurdres, very aesthetic, detailed, masterpiece::, "
        "20::highly finished::, 10::ultra detailed::, 5::masterpiece::, 5::best quality::, "
        "2.4::kidmo::, 1.2::omone hokoma agm::, 1.1::dino, wanke, liduke::, "
        "0.8::rurudo, mignon, artist:pottsness, artist:toosaka asagi::, "
        "0.7::misaka_12003-gou::, "
        "0.6::artist:chocoan, artist:ciloranko, artist:rhasta, artist:sho_sho_lwlw::, "
        "dino_(dinoartforame), agoto, akakura, "
        "year 2025, textless version, no text, The image is highly intricate finished drawn. "
        "1.35::A highly finished photo-style artwork that has graphic texture, realistic skin surface, "
        "and lifelike flesh with little obliques::, smooth line, glossy skin, realistic, 4k, "
        "1.63::photorealistic::, 1.63::photo(medium)::, 3::simple background::, 2::depth of field::, "
        "1.5::vivid color, lively color::, desaturated, muted tones, cinematic desaturation, "
        "pale aesthetic, silver-toned, -2::green::, -1.5::vibrant, colorful, saturated::"
    ),
    "lolita25d": (
        "20::best quality, absurdres, very aesthetic, detailed, masterpiece::, "
        "20::highly finished::, 10::ultra detailed::, 5::masterpiece::, 5::best quality::, "
        "2.4::kidmo::, 1.2::omone hokoma agm::, 1.1::dino, wanke, liduke::, "
        "0.8::rurudo, mignon, artist:pottsness, artist:toosaka asagi::, "
        "0.7::misaka_12003-gou::, "
        "0.6::artist:chocoan, artist:ciloranko, artist:rhasta, artist:sho_sho_lwlw::, "
        "dino_(dinoartforame), agoto, akakura, "
        "0.9::rurudo(Only body shape), mignon(Only body shape)::, "
        "year 2025, textless version, {{petite,loli}}, Petite figure, no text, "
        "1.35::A highly finished photo-style artwork that has graphic texture, realistic skin surface, "
        "and lifelike flesh with little obliques::, smooth line, glossy skin, realistic, 4k, "
        "1.63::photorealistic::, 1.63::photo(medium)::, 3::simple background::, 2::depth of field::, "
        "1.5::vivid color, lively color::, desaturated, muted tones, "
        "-2::green::, -1.5::vibrant, colorful, saturated::"
    ),
    "anime": (
        "1.4::asanagi::,{{{{{artist:asanagi}}}}},1.2::xiaoluo_xl::,"
        "1.3::Artist: misaka_12003-gou::,"
        "1.2::Artist:shexyo::,0.7::Artist:b.sa_(bbbs)::,1::Artist:qiandaiyiyu::,"
        "1.05::artist:natedecock::,1.05::artist:kunaboto::,0.75::artist:kandata_nijou::,"
        "1.05::artist:zer0.zer0::,1.05::artist:jasony::,0.75::misaka_12003-gou::, "
        "dino_(dinoartforame), wanke, liduke, year 2025, realistic, 4k, -2::green::, "
        "{textless version, The image is highly intricate finished drawn,write realistically,true to life}, "
        "1.35::A highly finished photo-style artwork that has lively color, graphic texture, "
        "realistic skin surface, and lifelike flesh with little obliques::, "
        "1.63::photorealistic::,3::age slider::,1.63::photo(medium)::, "
        "2::best quality, absurdres, very aesthetic, detailed, masterpiece::,"
        "-4::Muscle definition, abs::"
    ),
    "galgame": (
        "artist:ningen_mame,, noyu_(noyu23386566),, toosaka asagi,, location,\\n"
        "20::best quality, absurdres, very aesthetic, detailed, masterpiece::,:,, "
        "very aesthetic, masterpiece, no text,"
    ),
}

DEFAULT_NEGATIVE = (
    "{{bad anatomy}},{bad feet},bad hands,{{{bad proportions}}},{blurry},cloned face,cropped,"
    "{{{deformed}}},{{{disfigured}}},error,{{{extra arms}}},{extra digit},{{{extra legs}}},extra limbs,"
    "{{extra limbs}},{fewer digits},{{{fused fingers}}},gross proportions,ink eyes,ink hair,"
    "jpeg artifacts,{{{{long neck}}}},low quality,{malformed limbs},{{missing arms}},{missing fingers},"
    "{{missing legs}},{{{more than 2 nipples}}},mutated hands,{{{mutation}}},normal quality,owres,"
    "{{poorly drawn face}},{{poorly drawn hands}},reen eyes,signature,text,{{too many fingers}},"
    "{{{ugly}}},username,uta,watermark,worst quality,{{{more than 2 legs}}},"
    "awkward hand sign,weird hand gesture,contorted hand,unnatural finger pose,deformed hand gesture,"
    "{shaka},{hang loose},{{rock on}},{shaka sign}"
)

NSFW_SAFE_MODEL = "nai-diffusion-4-5-curated"
NSFW_FULL_MODEL = "nai-diffusion-4-5-full"

# API 文档常用模型（固定可选列表）
AVAILABLE_MODELS: List[str] = [
    "nai-diffusion-4-5-full",
    "nai-diffusion-4-5-curated",
    "nai-diffusion-4-full",
]
