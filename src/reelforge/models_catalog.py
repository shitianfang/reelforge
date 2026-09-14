"""The model catalog: single source of truth for what the dashboard lists,
what the playground can run, and what each call is estimated to cost.

`selectable` entries can be generated from the playground and MUST carry a
real price estimator; display-only rows (selectable=False) are informational
until an adapter + verified price is added. Endpoint slugs verified against
fal's public OpenAPI on 2026-09-12; H3-family discount ends 2026-09-14 (x4).
"""

H3_TURBO_PRICE = {"480P": 0.00625, "768P": 0.01, "1080P": 0.02}
H3_MAX_PRICE = {"480P": 0.0125, "768P": 0.02, "1080P": 0.04}
SEEDANCE_DIMS = {"480P": (854, 480), "768P": (1280, 720), "1080P": (1920, 1080)}

CATALOG = [
    # ---- images -----------------------------------------------------------
    {"id": "image_fast", "kind": "image", "family": "wh", "selectable": True,
     "endpoint": "fal-ai/z-image/turbo", "tier": "草稿档",
     "label": "Z-Image Turbo", "price": "$0.005/百万像素，竖屏草稿约 ¥0.03",
     "pros": "便宜到可以随便试、约 3 秒出图、真实感不错",
     "cons": "细节和图内文字不如高档模型",
     "usage": "默认主力：一个想法先生 3–5 张挑，不心疼钱"},
    {"id": "image_flux2", "kind": "image", "family": "wh", "selectable": True,
     "endpoint": "fal-ai/flux-2", "tier": "均衡档",
     "label": "FLUX 2", "price": "$0.012/百万像素，竖屏一张约 ¥0.18",
     "pros": "写实度和提示词服从性口碑最好，摄影感强",
     "cons": "比 Z-Image 贵一倍多，速度中等",
     "usage": "写实、摄影风格的首选升级档"},
    {"id": "image_nano", "kind": "image", "family": "aspect", "selectable": True,
     "endpoint": "fal-ai/nano-banana", "tier": "均衡档",
     "label": "Nano Banana（Google）", "price": "$0.039/张（约 ¥0.28）",
     "pros": "谷歌出品，人物一致性和改图能力出名",
     "cons": "只能选宽高比，不能指定精确像素",
     "usage": "做系列内容、要主角长得稳定时用它"},
    {"id": "image_high", "kind": "image", "family": "seedream", "selectable": True,
     "endpoint": "fal-ai/bytedance/seedream/v5/lite/text-to-image", "tier": "质量档",
     "label": "Seedream 5 Lite", "price": "$0.035/张（约 ¥0.25）",
     "pros": "商业海报质感、画面里写字最准、最大可出 3072×3072 超清大图",
     "cons": "比草稿档贵 7 倍，速度稍慢",
     "usage": "草稿档挑中构图后，同一段提示词换它出正式版"},
    {"id": "image_gpt15", "kind": "image", "family": None, "selectable": False,
     "endpoint": "fal-ai/gpt-image-1.5", "tier": "旗舰档",
     "label": "GPT Image 1.5（OpenAI）", "price": "按质量档计价，见 fal 模型页",
     "pros": "复杂场景构图盲测榜前列",
     "cons": "贵、慢，尺寸只有三种",
     "usage": "个别封面级画面再考虑；暂未接入一键生成"},
    {"id": "image_qwen", "kind": "image", "family": None, "selectable": False,
     "endpoint": "fal-ai/qwen-image", "tier": "草稿档",
     "label": "Qwen Image（阿里）", "price": "见 fal 模型页",
     "pros": "中文文字渲染友好，支持 LoRA",
     "cons": "写实感一般",
     "usage": "画面里要写中文字时的备选；暂未接入"},
    # ---- video ------------------------------------------------------------
    {"id": "video_h3_turbo", "kind": "video", "family": "h3", "selectable": True,
     "endpoint": "minimax/h3-max-turbo/image-to-video",
     "endpoint_t2v": "minimax/h3-max-turbo/text-to-video", "tier": "性价比王",
     "label": "H3 Max Turbo（MiniMax）",
     "price": "480P $0.00625/秒 · 768P $0.01/秒 · 1080P $0.02/秒",
     "pros": "带声音、最便宜的新一代视频，4–15 秒",
     "cons": "比非 Turbo 档细节略糙；折扣 2026-09-14 到期后涨 4 倍",
     "usage": "试想法和量产的默认档：480P 试，768P 出片"},
    {"id": "video_h3_max", "kind": "video", "family": "h3", "selectable": True,
     "endpoint": "minimax/h3-max/image-to-video",
     "endpoint_t2v": "minimax/h3-max/text-to-video", "tier": "质量档",
     "label": "H3 Max（MiniMax·非 Turbo）",
     "price": "480P $0.0125/秒 · 768P $0.02/秒 · 1080P $0.04/秒（Turbo 的 2 倍）",
     "pros": "同一家族的完整算力档，画面细节和运动更稳",
     "cons": "价格翻倍；折扣同样 2026-09-14 到期",
     "usage": "Turbo 挑中的镜头，用它重渲出正式版"},
    {"id": "video_seedance", "kind": "video", "family": "seedance", "selectable": True,
     "endpoint": "fal-ai/bytedance/seedance/v1.5/pro/image-to-video",
     "endpoint_t2v": "fal-ai/bytedance/seedance/v1.5/pro/text-to-video", "tier": "均衡档",
     "label": "Seedance 1.5 Pro（字节）",
     "price": "按像素×时长计价，720p 5 秒约 $0.26（含音频）",
     "pros": "原生对白、音效、口型同步，4–12 秒",
     "cons": "比 H3 Turbo 贵，价格按 token 略难心算（页面会帮你算）",
     "usage": "要角色开口说话的镜头选它"},
    {"id": "video_seedance25", "kind": "video", "family": "seedance25", "selectable": True,
     "endpoint": "bytedance/seedance-2.5/image-to-video",
     "endpoint_t2v": "bytedance/seedance-2.5/text-to-video", "tier": "旗舰档",
     "label": "Seedance 2.5（字节·旗舰）",
     "price": "$0.0214/千 token，720p 5 秒约 $2.31；1080p 费率以 fal 页为准",
     "pros": "唯一能原生一次生成 30 秒的档；音画同一空间生成、口型同步最好；提示词服从再提 20%",
     "cons": "贵：720p 约 $0.47/秒，是 1.5 Pro 的 9 倍",
     "usage": "15–30 秒一镜到底、或口型要求苛刻的重点片才用"},
    {"id": "video_hailuo23", "kind": "video", "family": None, "selectable": False,
     "endpoint": "fal-ai/minimax/hailuo-2.3/standard/image-to-video", "tier": "上一代",
     "label": "Hailuo 2.3（MiniMax·上一代）", "price": "见 fal 模型页",
     "pros": "物理运动真实感有口碑，6/10 秒两档",
     "cons": "上一代，无声音，可控参数少",
     "usage": "H3 效果不满意时的对照组；暂未接入"},
    {"id": "video_kling3", "kind": "video", "family": None, "selectable": False,
     "endpoint": "fal-ai/kling-video/v3/standard/image-to-video", "tier": "旗舰档",
     "label": "Kling 3（快手）", "price": "见 fal 模型页",
     "pros": "运动控制和人物表演强",
     "cons": "价格高",
     "usage": "特写表演镜头的备选；暂未接入"},
    {"id": "video_veo3", "kind": "video", "family": None, "selectable": False,
     "endpoint": "fal-ai/veo3/fast", "tier": "旗舰档",
     "label": "Veo 3 Fast（Google）", "price": "见 fal 模型页（按秒，较贵）",
     "pros": "对话型 vlog 爆款的鼻祖，音画同步好",
     "cons": "贵，风格偏西方",
     "usage": "英文对话类爆款再考虑；暂未接入"},
    {"id": "video_sora2", "kind": "video", "family": None, "selectable": False,
     "endpoint": "fal-ai/sora-2/text-to-video", "tier": "旗舰档",
     "label": "Sora 2（OpenAI）", "price": "见 fal 模型页",
     "pros": "叙事连贯性强",
     "cons": "贵、排队、审核严",
     "usage": "长叙事再考虑；暂未接入"},
    # ---- finishing (post) --------------------------------------------------
    {"id": "video_finish", "kind": "finish", "family": "topaz", "selectable": False,
     "endpoint": "fal-ai/topaz/upscale/video", "tier": "后期",
     "label": "Topaz Video（插帧/放大）",
     "price": "输出每秒：≤720p $0.01 · ≤1080p $0.02 · 更高 $0.08；60fps 输出价格×2",
     "pros": "GPU 插帧到 60fps，质量远好于本机 minterpolate，重活不占本机内存",
     "cons": "按输出时长计费",
     "usage": "reelforge finish <in> <out>：成片的 60fps 收尾（CLI 专用，不进 playground）"},
    # ---- music / audio ----------------------------------------------------
    {"id": "music", "kind": "music", "family": "mmx_music", "selectable": True,
     "endpoint": "minimax/music-3", "tier": "性价比王",
     "label": "MiniMax Music 3", "price": "$0.002/秒，30 秒约 ¥0.43",
     "pros": "便宜，描述曲风即可，可写歌词",
     "cons": "不能指定精确 BPM",
     "usage": "批量卡点任务的默认配乐"},
    {"id": "music_el", "kind": "music", "family": "el_music", "selectable": True,
     "endpoint": "fal-ai/elevenlabs/music", "tier": "质量档",
     "label": "ElevenLabs Music", "price": "$0.6/分钟（$0.01/秒），30 秒约 ¥2.2",
     "pros": "音乐质感和结构感更专业，可强制纯音乐",
     "cons": "是 MiniMax 的 5 倍价",
     "usage": "重点视频的配乐升级档"},
    {"id": "audio_el_tts", "kind": "audio", "family": None, "selectable": False,
     "endpoint": "fal-ai/elevenlabs/tts/eleven-v3", "tier": "配音",
     "label": "ElevenLabs 配音 TTS（v3·多语·Turbo）", "price": "见 fal 模型页",
     "pros": "旁白、角色配音，多语种",
     "cons": "尚未接入流水线",
     "usage": "路线图：POV vlog 的角色说话声"},
    {"id": "audio_el_sfx", "kind": "audio", "family": None, "selectable": False,
     "endpoint": "fal-ai/elevenlabs/sound-effects", "tier": "音效",
     "label": "ElevenLabs 音效", "price": "见 fal 模型页",
     "pros": "文字描述生成音效",
     "cons": "尚未接入流水线",
     "usage": "路线图：卡点转场音效"},
]

_BY_ID = {m["id"]: m for m in CATALOG}


def get_model(model_id: str) -> dict:
    if model_id not in _BY_ID:
        raise KeyError(f"unknown model id '{model_id}'")
    return _BY_ID[model_id]


def est_for(model_id: str, *, width: int = 0, height: int = 0,
            duration: int = 0, resolution: str = "768P", fps: int = 0) -> float:
    """USD estimate for one generation; selectable models only."""
    m = get_model(model_id)
    fam = m["family"]
    if fam == "wh":
        per_mp = 0.005 if model_id == "image_fast" else 0.012
        return per_mp * (width * height) / 1_000_000
    if fam == "seedream":
        return 0.035
    if fam == "aspect":
        return 0.039
    if fam == "h3":
        table = H3_TURBO_PRICE if model_id == "video_h3_turbo" else H3_MAX_PRICE
        return table[resolution] * duration
    if fam in ("seedance", "seedance25"):
        w, h = SEEDANCE_DIMS[resolution]
        max_s = 12 if fam == "seedance" else 30  # duration clamps mirror the adapters
        tokens = w * h * 24 * max(4, min(max_s, duration)) / 1024
        # 1.5 Pro: $2.4/M tokens with audio; 2.5: $0.0214/1K tokens
        return tokens / 1_000_000 * 2.4 if fam == "seedance" else tokens * 0.0000214
    if fam == "topaz":
        # billed per OUTPUT second by output height; 60fps output doubles it
        per_s = 0.01 if height <= 720 else (0.02 if height <= 1080 else 0.08)
        return per_s * duration * (2 if fps >= 60 else 1)
    if fam == "mmx_music":
        return 0.002 * duration
    if fam == "el_music":
        return 0.01 * duration
    raise KeyError(f"model '{model_id}' has no estimator (not selectable)")
