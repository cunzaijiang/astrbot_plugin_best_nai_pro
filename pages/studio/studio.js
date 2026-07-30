/**
 * 魔法绘图 Studio — 前端逻辑 v0.3.1
 * 文生图 + 局部重绘（遮罩编辑 / 非标尺寸裁剪适配）
 * API 前缀: studio/*
 */
(function () {
  "use strict";

  const DEFAULT_MODELS = [
    "nai-diffusion-4-5-full",
    "nai-diffusion-4-5-curated",
    "nai-diffusion-4-full",
  ];
  const VALID_SIZES = [
    [832, 1216],
    [1216, 832],
    [1024, 1024],
  ];
  const SIZE_LABEL = {
    "832x1216": "竖图",
    "1216x832": "横图",
    "1024x1024": "方图",
  };

  const $ = (id) => document.getElementById(id);
  const els = {
    naiPrompt: $("naiPrompt"),
    nlPrompt: $("nlPrompt"),
    inpaintNaiPrompt: $("inpaintNaiPrompt"),
    inpaintNlPrompt: $("inpaintNlPrompt"),
    sampler: $("sampler"),
    size: $("size"),
    sizeSeg: $("sizeSeg"),
    steps: $("steps"),
    scale: $("scale"),
    noiseSchedule: $("noiseSchedule"),
    model: $("model"),
    seed: $("seed"),
    quality: $("quality"),
    ucPreset: $("ucPreset"),
    varietyBoost: $("varietyBoost"),
    cfgRescale: $("cfgRescale"),
    style: $("style"),
    customArtistsWrap: $("customArtistsWrap"),
    customArtists: $("customArtists"),
    negative: $("negative"),
    loadDefaultNegative: $("loadDefaultNegative"),
    generateBtn: $("generateBtn"),
    generateLabel: $("generateLabel"),
    resetBtn: $("resetBtn"),
    tokenPill: $("tokenPill"),
    endpointPill: $("endpointPill"),
    resultMeta: $("resultMeta"),
    emptyState: $("emptyState"),
    loadingState: $("loadingState"),
    loadingText: $("loadingText"),
    errorState: $("errorState"),
    errorMsg: $("errorMsg"),
    retryBtn: $("retryBtn"),
    resultWrap: $("resultWrap"),
    resultImage: $("resultImage"),
    downloadBtn: $("downloadBtn"),
    mergeInfo: $("mergeInfo"),
    mergeSteps: $("mergeSteps"),
    toggleTrace: $("toggleTrace"),
    modeSwitch: $("modeSwitch"),
    modeGlider: $("modeGlider"),
    modePanels: $("modePanels"),
    inpaintUploader: $("inpaintUploader"),
    inpaintFile: $("inpaintFile"),
    inpaintEditorWrap: $("inpaintEditorWrap"),
    inpaintCanvas: $("inpaintCanvas"),
    inpaintMeta: $("inpaintMeta"),
    inpaintStrength: $("inpaintStrength"),
    inpaintStrengthLabel: $("inpaintStrengthLabel"),
    inpaintInvert: $("inpaintInvert"),
    brushSize: $("brushSize"),
    brushSizeLabel: $("brushSizeLabel"),
    toolBrush: $("toolBrush"),
    toolEraser: $("toolEraser"),
    toolLasso: $("toolLasso"),
    toolUndo: $("toolUndo"),
    toolClear: $("toolClear"),
    toolRemoveImage: $("toolRemoveImage"),
  };

  let isGenerating = false;
  let lastRequestBody = null;
  let lastB64 = null;
  let traceExpanded = false;
  let currentMode = "txt2img"; // txt2img | inpaint

  // inpaint mask state
  const inpaint = {
    imageDataUrl: "",
    maskDataUrl: "",
    width: 0,
    height: 0,
    sizeLabel: "",
    sizeArray: null,
    baseImage: null,
    strokes: [],
    drawing: false,
    tool: "brush", // brush | eraser | lasso
    brushSize: 30,
  };

  const show = (el) => el && el.classList.remove("hidden");
  const hide = (el) => el && el.classList.add("hidden");

  async function getBridge() {
    const deadline = Date.now() + 5000;
    while (!window.AstrBotPluginPage && Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 100));
    }
    if (!window.AstrBotPluginPage) {
      throw new Error("Bridge SDK 未就绪，请从 AstrBot 后台的插件拓展页打开 Studio");
    }
    await window.AstrBotPluginPage.ready();
    return window.AstrBotPluginPage;
  }

  const CACHE_FIELDS = [
    "naiPrompt", "nlPrompt", "sampler", "size", "steps", "scale",
    "noiseSchedule", "model", "seed", "ucPreset", "cfgRescale",
    "style", "customArtists", "negative",
    "inpaintNaiPrompt", "inpaintNlPrompt",
  ];

  let saveTimer = null;
  function collectCachePayload() {
    const data = {};
    CACHE_FIELDS.forEach((key) => {
      const el = els[key];
      if (el) data[key] = el.value;
    });
    data.quality = els.quality.checked;
    data.varietyBoost = els.varietyBoost.checked;
    data.mode = currentMode;
    data.inpaintStrength = els.inpaintStrength ? els.inpaintStrength.value : "1";
    data.inpaintInvert = !!(els.inpaintInvert && els.inpaintInvert.checked);
    data.brushSize = els.brushSize ? els.brushSize.value : "30";
    data.sections = {};
    document.querySelectorAll(".block[data-section]").forEach((block) => {
      data.sections[block.dataset.section] = block.dataset.open === "true";
    });
    data.traceExpanded = traceExpanded;
    return data;
  }

  function saveCache() {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(async () => {
      try {
        const bridge = await getBridge();
        await bridge.apiPost("studio/save_cache", collectCachePayload());
      } catch (e) {
        console.warn("[Studio] cache save failed", e);
      }
    }, 400);
  }

  function setSectionOpen(block, open) {
    block.dataset.open = open ? "true" : "false";
    const head = block.querySelector(".block-head");
    if (head) head.setAttribute("aria-expanded", open ? "true" : "false");
  }

  function applySectionState(sections) {
    document.querySelectorAll(".block[data-section]").forEach((block) => {
      const key = block.dataset.section;
      let open;
      if (sections && typeof sections[key] === "boolean") open = sections[key];
      else open = block.dataset.open === "true";
      setSectionOpen(block, open);
    });
  }

  function bindSections() {
    document.querySelectorAll(".block-head").forEach((btn) => {
      btn.addEventListener("click", () => {
        const block = btn.closest(".block");
        if (!block) return;
        setSectionOpen(block, block.dataset.open !== "true");
        saveCache();
      });
    });
  }

  async function loadCache() {
    try {
      const bridge = await getBridge();
      const resp = await bridge.apiGet("studio/load_cache");
      const data = (resp && resp.data) ? resp.data : resp;
      if (!data || typeof data !== "object") {
        applySectionState(null);
        return false;
      }
      CACHE_FIELDS.forEach((key) => {
        const el = els[key];
        if (el && data[key] != null) el.value = data[key];
      });
      if (typeof data.quality === "boolean") els.quality.checked = data.quality;
      if (typeof data.varietyBoost === "boolean") els.varietyBoost.checked = data.varietyBoost;
      if (data.inpaintStrength != null && els.inpaintStrength) {
        els.inpaintStrength.value = data.inpaintStrength;
        updateStrengthLabel();
      }
      if (typeof data.inpaintInvert === "boolean" && els.inpaintInvert) {
        els.inpaintInvert.checked = data.inpaintInvert;
      }
      if (data.brushSize != null && els.brushSize) {
        els.brushSize.value = data.brushSize;
        inpaint.brushSize = parseInt(data.brushSize, 10) || 30;
        updateBrushLabel();
      }
      syncSizeSeg(els.size.value);
      applySectionState(data.sections || null);
      if (typeof data.traceExpanded === "boolean") traceExpanded = data.traceExpanded;
      if (data.mode === "inpaint" || data.mode === "txt2img") {
        setMode(data.mode, false);
      }
      return true;
    } catch (e) {
      console.warn("[Studio] cache load failed", e);
      applySectionState(null);
      return false;
    }
  }

  function syncSizeSeg(value) {
    els.size.value = value || "竖图";
    if (!els.sizeSeg) return;
    els.sizeSeg.querySelectorAll(".seg-item").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.value === els.size.value);
    });
  }

  function fillModelOptions(options, selected) {
    const list =
      Array.isArray(options) && options.length ? options.slice() : DEFAULT_MODELS.slice();
    const current = selected || els.model.value || DEFAULT_MODELS[0];
    if (current && list.indexOf(current) < 0) list.unshift(current);
    const prev = els.model.value;
    els.model.innerHTML = "";
    list.forEach((id) => {
      const opt = document.createElement("option");
      opt.value = id;
      opt.textContent = id;
      els.model.appendChild(opt);
    });
    if (list.indexOf(current) >= 0) els.model.value = current;
    else if (list.indexOf(prev) >= 0) els.model.value = prev;
    else if (list.length) els.model.value = list[0];
  }

  const STYLE_LABELS = {
    vertical: "条漫清新",
    comicDoujin: "同人分镜",
    r18: "半立体唯美",
    lolita25d: "半立体幼态",
    anime: "里番本格",
    galgame: "视觉小说",
    custom: "自定义",
  };

  function applyStyleLabels(styleMap) {
    if (!styleMap || typeof styleMap !== "object") return;
    const select = els.style;
    if (!select) return;
    const current = select.value;
    Array.from(select.options).forEach((opt) => {
      if (styleMap[opt.value]) {
        let label = styleMap[opt.value];
        if (label.endsWith("风") && opt.value !== "custom") label = label.slice(0, -1);
        opt.textContent = label;
      }
    });
    select.value = current;
    Object.keys(styleMap).forEach((k) => {
      STYLE_LABELS[k] =
        styleMap[k].endsWith("风") && k !== "custom"
          ? styleMap[k].slice(0, -1)
          : styleMap[k];
    });
  }

  async function loadConfigStatus() {
    try {
      const bridge = await getBridge();
      const resp = await bridge.apiGet("studio/config");
      const config = (resp && resp.data) ? resp.data : resp;
      if (config.image_gen_key === "已配置") {
        els.tokenPill.textContent = "KEY · OK";
        els.tokenPill.dataset.state = "ok";
      } else {
        els.tokenPill.textContent = "KEY · 未配置";
        els.tokenPill.dataset.state = "err";
      }
      els.endpointPill.textContent = config.base_url || "endpoint —";
      fillModelOptions(config.model_options, config.model);
      if (config.image_styles_options) applyStyleLabels(config.image_styles_options);
      if (config.image_style) els.style.value = config.image_style;
      if (config.image_size) syncSizeSeg(config.image_size);
      if (config.sampler) els.sampler.value = config.sampler;
      if (config.steps != null) els.steps.value = config.steps;
      if (config.scale != null) els.scale.value = config.scale;
    } catch (err) {
      els.tokenPill.textContent = "KEY · 加载失败";
      els.tokenPill.dataset.state = "err";
      fillModelOptions(DEFAULT_MODELS, els.model.value);
    }
  }

  function toggleCustomArtists() {
    if (els.style.value === "custom") show(els.customArtistsWrap);
    else hide(els.customArtistsWrap);
    saveCache();
  }

  // ---- mode switch ----
  function setMode(mode, animate) {
    currentMode = mode === "inpaint" ? "inpaint" : "txt2img";
    if (els.modeSwitch) els.modeSwitch.dataset.mode = currentMode;
    if (els.modePanels) {
      // re-trigger panel animation
      if (animate !== false) {
        els.modePanels.classList.remove("animating");
        // force reflow
        void els.modePanels.offsetWidth;
      }
      els.modePanels.dataset.mode = currentMode;
    }
    document.querySelectorAll(".mode-btn").forEach((btn) => {
      const on = btn.dataset.mode === currentMode;
      btn.classList.toggle("active", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
    });
    if (els.generateLabel) {
      els.generateLabel.textContent = currentMode === "inpaint" ? "重绘" : "生成";
    }
    if (els.emptyState) {
      const hint = els.emptyState.querySelector(".stage-hint");
      const title = els.emptyState.querySelector("h2");
      if (title) title.textContent = currentMode === "inpaint" ? "等待局部重绘" : "等待生成";
      if (hint) {
        hint.textContent =
          currentMode === "inpaint"
            ? "上传原图并涂抹白色区域，再点重绘"
            : "在右侧填写提示词，或直接 Ctrl + Enter";
      }
    }
    saveCache();
  }

  // ---- inpaint mask editor ----
  function updateBrushLabel() {
    if (els.brushSizeLabel) els.brushSizeLabel.textContent = inpaint.brushSize + "px";
  }
  function updateStrengthLabel() {
    if (els.inpaintStrengthLabel && els.inpaintStrength) {
      els.inpaintStrengthLabel.textContent = Number(els.inpaintStrength.value).toFixed(2);
    }
  }

  function setTool(tool) {
    inpaint.tool = tool;
    [
      [els.toolBrush, "brush"],
      [els.toolEraser, "eraser"],
      [els.toolLasso, "lasso"],
    ].forEach(([btn, name]) => {
      if (btn) btn.classList.toggle("on", tool === name);
    });
  }

  function nearestSize(w, h) {
    const key = w + "x" + h;
    if (SIZE_LABEL[key]) {
      return { label: SIZE_LABEL[key], array: [w, h], exact: true };
    }
    let best = VALID_SIZES[0];
    let bestDiff = Infinity;
    VALID_SIZES.forEach(([sw, sh]) => {
      const diff =
        Math.abs(sw / sh - w / h) +
        Math.abs(sw - w) / 4000 +
        Math.abs(sh - h) / 4000;
      if (diff < bestDiff) {
        bestDiff = diff;
        best = [sw, sh];
      }
    });
    return {
      label: SIZE_LABEL[best[0] + "x" + best[1]] || best.join("x"),
      array: best,
      exact: false,
    };
  }

  /**
   * 把任意图适配到目标尺寸。
   * mode: cover（裁剪填满）| contain（完整图 + 黑边）| stretch（拉伸变形）
   * offset: {x,y} 相对中心的像素偏移（仅 cover / contain 有效）
   */
  function fitImageToSize(img, targetW, targetH, mode, offset) {
    const c = document.createElement("canvas");
    c.width = targetW;
    c.height = targetH;
    const ctx = c.getContext("2d");
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, targetW, targetH);

    const m = mode || "cover";
    const ox = (offset && offset.x) || 0;
    const oy = (offset && offset.y) || 0;

    if (m === "stretch") {
      ctx.drawImage(img, 0, 0, targetW, targetH);
      return c;
    }

    const scale =
      m === "contain"
        ? Math.min(targetW / img.width, targetH / img.height)
        : Math.max(targetW / img.width, targetH / img.height);
    const dw = img.width * scale;
    const dh = img.height * scale;
    // 偏移限制在「图片能盖住目标」范围内（cover 才有意义；contain 允许少量拖动）
    let dx = (targetW - dw) / 2 + ox;
    let dy = (targetH - dh) / 2 + oy;
    if (m === "cover") {
      // 不允许露出黑边：图片必须盖住画布
      const minX = targetW - dw; // ≤ 0
      const minY = targetH - dh;
      dx = Math.min(0, Math.max(minX, dx));
      dy = Math.min(0, Math.max(minY, dy));
    }
    ctx.drawImage(img, dx, dy, dw, dh);
    return c;
  }

  function fitImageToDataURL(img, targetW, targetH, mode, offset) {
    return fitImageToSize(img, targetW, targetH, mode, offset).toDataURL(
      "image/png"
    );
  }

  // ---- 非标准尺寸：裁剪/缩放对话框 ----
  function openFitDialog(srcImg, suggested) {
    return new Promise((resolve) => {
      const state = {
        mode: "cover", // cover | contain | stretch
        target: suggested.array.slice(),
        offset: { x: 0, y: 0 },
        dragging: false,
        lastX: 0,
        lastY: 0,
      };

      const modal = document.createElement("div");
      modal.className = "fit-modal";
      modal.innerHTML =
        '<div class="fit-dialog" role="dialog" aria-modal="true">' +
        "<h3>适配绘图尺寸</h3>" +
        '<p class="fit-sub">原图 <strong id="fitSrcSize"></strong> 不是 NAI 标准尺寸，' +
        "需要先裁剪 / 缩放后才能局部重绘。</p>" +
        '<div class="fit-preview-wrap" id="fitPreviewWrap">' +
        '<canvas id="fitPreviewCanvas"></canvas>' +
        "</div>" +
        '<div class="fit-row"><span class="label">目标尺寸</span>' +
        '<div class="fit-seg" id="fitSizeSeg"></div></div>' +
        '<div class="fit-row"><span class="label">适配方式</span>' +
        '<div class="fit-seg" id="fitModeSeg">' +
        '<button type="button" data-mode="cover" class="on">裁剪填满</button>' +
        '<button type="button" data-mode="contain">完整缩放</button>' +
        '<button type="button" data-mode="stretch">拉伸</button>' +
        "</div></div>" +
        '<p class="fit-hint" id="fitHint"></p>' +
        '<div class="fit-actions">' +
        '<button type="button" class="ghost" id="fitCancel">取消</button>' +
        '<button type="button" class="accent" id="fitConfirm">应用到编辑器</button>' +
        "</div></div>";
      document.body.appendChild(modal);

      const srcLabel = modal.querySelector("#fitSrcSize");
      const previewWrap = modal.querySelector("#fitPreviewWrap");
      const previewCanvas = modal.querySelector("#fitPreviewCanvas");
      const sizeSeg = modal.querySelector("#fitSizeSeg");
      const modeSeg = modal.querySelector("#fitModeSeg");
      const hint = modal.querySelector("#fitHint");
      const btnCancel = modal.querySelector("#fitCancel");
      const btnConfirm = modal.querySelector("#fitConfirm");

      srcLabel.textContent = srcImg.width + "×" + srcImg.height;

      VALID_SIZES.forEach(([w, h]) => {
        const key = w + "x" + h;
        const btn = document.createElement("button");
        btn.type = "button";
        btn.dataset.w = String(w);
        btn.dataset.h = String(h);
        btn.textContent =
          (SIZE_LABEL[key] || key) + " " + w + "×" + h;
        if (w === state.target[0] && h === state.target[1]) {
          btn.classList.add("on");
        }
        sizeSeg.appendChild(btn);
      });

      function modeHint() {
        if (state.mode === "cover") {
          hint.textContent = "裁剪填满：等比放大后居中裁剪，可拖动预览调整裁剪位置。";
        } else if (state.mode === "contain") {
          hint.textContent = "完整缩放：整图等比放入，不足处补黑边。";
        } else {
          hint.textContent = "拉伸：强制拉到目标尺寸，可能变形。";
        }
      }

      function redraw() {
        const [tw, th] = state.target;
        // 预览画布按目标比例缩放显示，最大边约 480
        const maxSide = 480;
        const viewScale = Math.min(1, maxSide / Math.max(tw, th));
        const vw = Math.round(tw * viewScale);
        const vh = Math.round(th * viewScale);
        // 先在目标分辨率上合成，再缩到预览
        const full = fitImageToSize(
          srcImg,
          tw,
          th,
          state.mode,
          state.offset
        );
        previewCanvas.width = vw;
        previewCanvas.height = vh;
        const ctx = previewCanvas.getContext("2d");
        ctx.imageSmoothingEnabled = true;
        ctx.clearRect(0, 0, vw, vh);
        ctx.drawImage(full, 0, 0, vw, vh);
        modeHint();
      }

      function setMode(mode) {
        state.mode = mode;
        state.offset = { x: 0, y: 0 };
        modeSeg.querySelectorAll("button").forEach((b) => {
          b.classList.toggle("on", b.dataset.mode === mode);
        });
        redraw();
      }

      sizeSeg.addEventListener("click", (e) => {
        const btn = e.target.closest("button");
        if (!btn) return;
        state.target = [
          parseInt(btn.dataset.w, 10),
          parseInt(btn.dataset.h, 10),
        ];
        state.offset = { x: 0, y: 0 };
        sizeSeg.querySelectorAll("button").forEach((b) =>
          b.classList.toggle("on", b === btn)
        );
        redraw();
      });
      modeSeg.addEventListener("click", (e) => {
        const btn = e.target.closest("button");
        if (!btn) return;
        setMode(btn.dataset.mode);
      });

      // 拖动调整 cover 裁剪位置（映射到目标像素坐标）
      function onPointerDown(e) {
        if (state.mode === "stretch") return;
        state.dragging = true;
        previewWrap.classList.add("dragging");
        const pt = e.touches ? e.touches[0] : e;
        state.lastX = pt.clientX;
        state.lastY = pt.clientY;
        e.preventDefault();
      }
      function onPointerMove(e) {
        if (!state.dragging) return;
        const pt = e.touches ? e.touches[0] : e;
        const dx = pt.clientX - state.lastX;
        const dy = pt.clientY - state.lastY;
        state.lastX = pt.clientX;
        state.lastY = pt.clientY;
        const [tw, th] = state.target;
        const maxSide = 480;
        const viewScale = Math.min(1, maxSide / Math.max(tw, th));
        // 预览上的像素位移 → 目标分辨率位移
        state.offset.x += dx / viewScale;
        state.offset.y += dy / viewScale;
        redraw();
        e.preventDefault();
      }
      function onPointerUp() {
        state.dragging = false;
        previewWrap.classList.remove("dragging");
      }
      previewWrap.addEventListener("mousedown", onPointerDown);
      window.addEventListener("mousemove", onPointerMove);
      window.addEventListener("mouseup", onPointerUp);
      previewWrap.addEventListener("touchstart", onPointerDown, {
        passive: false,
      });
      window.addEventListener("touchmove", onPointerMove, { passive: false });
      window.addEventListener("touchend", onPointerUp);

      function cleanup(result) {
        window.removeEventListener("mousemove", onPointerMove);
        window.removeEventListener("mouseup", onPointerUp);
        window.removeEventListener("touchmove", onPointerMove);
        window.removeEventListener("touchend", onPointerUp);
        modal.remove();
        resolve(result);
      }

      btnCancel.addEventListener("click", () => cleanup(null));
      modal.addEventListener("click", (e) => {
        if (e.target === modal) cleanup(null);
      });
      btnConfirm.addEventListener("click", () => {
        const [tw, th] = state.target;
        const dataUrl = fitImageToDataURL(
          srcImg,
          tw,
          th,
          state.mode,
          state.offset
        );
        cleanup({
          dataUrl,
          width: tw,
          height: th,
          mode: state.mode,
          label: SIZE_LABEL[tw + "x" + th] || tw + "×" + th,
        });
      });

      redraw();
    });
  }

  async function applyInpaintSource(finalUrl, meta) {
    const finalImg = new Image();
    await new Promise((res, rej) => {
      finalImg.onload = res;
      finalImg.onerror = rej;
      finalImg.src = finalUrl;
    });

    inpaint.imageDataUrl = finalUrl;
    inpaint.baseImage = finalImg;
    inpaint.width = finalImg.width;
    inpaint.height = finalImg.height;
    inpaint.sizeArray = [finalImg.width, finalImg.height];
    inpaint.sizeLabel =
      SIZE_LABEL[finalImg.width + "x" + finalImg.height] ||
      finalImg.width + "×" + finalImg.height;
    inpaint.strokes = [];
    inpaint.maskDataUrl = "";

    if (SIZE_LABEL[finalImg.width + "x" + finalImg.height]) {
      syncSizeSeg(SIZE_LABEL[finalImg.width + "x" + finalImg.height]);
    }

    hide(els.inpaintUploader);
    show(els.inpaintEditorWrap);
    if (els.inpaintMeta) {
      const note = meta && meta.note ? " · " + meta.note : "";
      els.inpaintMeta.textContent =
        finalImg.width + "×" + finalImg.height + note;
    }
    initInpaintCanvas();
  }

  async function loadInpaintImage(dataUrl) {
    const img = new Image();
    await new Promise((res, rej) => {
      img.onload = res;
      img.onerror = rej;
      img.src = dataUrl;
    });
    const fit = nearestSize(img.width, img.height);
    if (fit.exact) {
      await applyInpaintSource(dataUrl, { note: "精确匹配" });
      return;
    }
    // 非标准尺寸 → 弹出裁剪/缩放对话框
    const result = await openFitDialog(img, fit);
    if (!result) {
      // 用户取消：保持上传区
      if (els.inpaintFile) els.inpaintFile.value = "";
      return;
    }
    const modeLabel =
      result.mode === "cover"
        ? "裁剪填满"
        : result.mode === "contain"
        ? "完整缩放"
        : "拉伸";
    await applyInpaintSource(result.dataUrl, {
      note: "已" + modeLabel + "到 " + result.label,
    });
  }

  function initInpaintCanvas() {
    const canvas = els.inpaintCanvas;
    if (!canvas || !inpaint.baseImage) return;
    canvas.width = inpaint.width;
    canvas.height = inpaint.height;
    canvas.style.width = "100%";
    redrawInpaint();
    saveMask();
  }

  function getOverlayMaskCanvas() {
    const mc = document.createElement("canvas");
    mc.width = inpaint.width;
    mc.height = inpaint.height;
    const mctx = mc.getContext("2d");
    mctx.fillStyle = "rgba(255,107,74,0.55)";
    mctx.strokeStyle = "rgba(255,107,74,0.55)";
    mctx.lineCap = "round";
    mctx.lineJoin = "round";
    for (const stroke of inpaint.strokes) {
      mctx.globalCompositeOperation = stroke.erase ? "destination-out" : "source-over";
      if (stroke.lasso) {
        if (stroke.points.length < 2) continue;
        mctx.beginPath();
        mctx.moveTo(stroke.points[0].x, stroke.points[0].y);
        for (let i = 1; i < stroke.points.length; i++) {
          mctx.lineTo(stroke.points[i].x, stroke.points[i].y);
        }
        if (stroke.closed) {
          mctx.closePath();
          mctx.fill();
        } else {
          mctx.lineWidth = 25;
          mctx.stroke();
        }
        continue;
      }
      mctx.lineWidth = stroke.size;
      if (stroke.points.length === 1) {
        mctx.beginPath();
        mctx.arc(stroke.points[0].x, stroke.points[0].y, stroke.size / 2, 0, Math.PI * 2);
        mctx.fill();
      } else {
        mctx.beginPath();
        mctx.moveTo(stroke.points[0].x, stroke.points[0].y);
        for (let i = 1; i < stroke.points.length; i++) {
          mctx.lineTo(stroke.points[i].x, stroke.points[i].y);
        }
        mctx.stroke();
      }
    }
    return mc;
  }

  function redrawInpaint() {
    const canvas = els.inpaintCanvas;
    if (!canvas || !inpaint.baseImage) return;
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(inpaint.baseImage, 0, 0);
    ctx.save();
    ctx.globalCompositeOperation = "source-over";
    ctx.drawImage(getOverlayMaskCanvas(), 0, 0);
    ctx.restore();
  }

  function saveMask() {
    if (!inpaint.baseImage) return;
    const mc = document.createElement("canvas");
    mc.width = inpaint.width;
    mc.height = inpaint.height;
    const mctx = mc.getContext("2d");
    mctx.fillStyle = "#000";
    mctx.fillRect(0, 0, mc.width, mc.height);
    mctx.fillStyle = "#fff";
    mctx.strokeStyle = "#fff";
    mctx.lineCap = "round";
    mctx.lineJoin = "round";
    for (const stroke of inpaint.strokes) {
      if (stroke.erase) {
        mctx.fillStyle = "#000";
        mctx.strokeStyle = "#000";
      } else {
        mctx.fillStyle = "#fff";
        mctx.strokeStyle = "#fff";
      }
      if (stroke.lasso) {
        if (stroke.points.length < 3) continue;
        mctx.beginPath();
        mctx.moveTo(stroke.points[0].x, stroke.points[0].y);
        for (let i = 1; i < stroke.points.length; i++) {
          mctx.lineTo(stroke.points[i].x, stroke.points[i].y);
        }
        mctx.closePath();
        mctx.fill();
        continue;
      }
      mctx.lineWidth = stroke.size;
      if (stroke.points.length === 1) {
        mctx.beginPath();
        mctx.arc(stroke.points[0].x, stroke.points[0].y, stroke.size / 2, 0, Math.PI * 2);
        mctx.fill();
      } else {
        mctx.beginPath();
        mctx.moveTo(stroke.points[0].x, stroke.points[0].y);
        for (let i = 1; i < stroke.points.length; i++) {
          mctx.lineTo(stroke.points[i].x, stroke.points[i].y);
        }
        mctx.stroke();
      }
    }
    // force RGB (no alpha) — magic-draw 同样处理
    const rgb = document.createElement("canvas");
    rgb.width = mc.width;
    rgb.height = mc.height;
    const rctx = rgb.getContext("2d", { alpha: false });
    rctx.drawImage(mc, 0, 0);
    inpaint.maskDataUrl = rgb.toDataURL("image/png");
  }

  function invertMask(dataUri) {
    return new Promise((resolve) => {
      const img = new Image();
      img.onload = () => {
        const c = document.createElement("canvas");
        c.width = img.width;
        c.height = img.height;
        const ctx = c.getContext("2d");
        ctx.drawImage(img, 0, 0);
        const d = ctx.getImageData(0, 0, c.width, c.height);
        for (let i = 0; i < d.data.length; i += 4) {
          d.data[i] = 255 - d.data[i];
          d.data[i + 1] = 255 - d.data[i + 1];
          d.data[i + 2] = 255 - d.data[i + 2];
        }
        ctx.putImageData(d, 0, 0);
        const rgb = document.createElement("canvas");
        rgb.width = c.width;
        rgb.height = c.height;
        const rctx = rgb.getContext("2d", { alpha: false });
        rctx.drawImage(c, 0, 0);
        resolve(rgb.toDataURL("image/png"));
      };
      img.src = dataUri;
    });
  }

  function maskPoint(ev) {
    const canvas = els.inpaintCanvas;
    const rect = canvas.getBoundingClientRect();
    const sx = canvas.width / rect.width;
    const sy = canvas.height / rect.height;
    const t = ev.touches ? ev.touches[0] : ev;
    return { x: (t.clientX - rect.left) * sx, y: (t.clientY - rect.top) * sy };
  }

  function inpaintStart(ev) {
    if (!inpaint.baseImage) return;
    inpaint.drawing = true;
    const p = maskPoint(ev);
    const isLasso = inpaint.tool === "lasso";
    inpaint.strokes.push({
      points: [p],
      size: inpaint.brushSize,
      erase: inpaint.tool === "eraser",
      lasso: isLasso,
    });
    if (inpaint.strokes.length > 200) inpaint.strokes.shift();
    redrawInpaint();
  }

  function inpaintMove(ev) {
    if (!inpaint.drawing) return;
    const p = maskPoint(ev);
    inpaint.strokes[inpaint.strokes.length - 1].points.push(p);
    redrawInpaint();
  }

  function inpaintEnd() {
    if (!inpaint.drawing) return;
    inpaint.drawing = false;
    const last = inpaint.strokes[inpaint.strokes.length - 1];
    if (last && last.lasso) {
      last.closed = true;
      redrawInpaint();
    }
    saveMask();
  }

  function clearInpaintImage() {
    inpaint.imageDataUrl = "";
    inpaint.maskDataUrl = "";
    inpaint.baseImage = null;
    inpaint.strokes = [];
    inpaint.width = 0;
    inpaint.height = 0;
    inpaint.sizeArray = null;
    show(els.inpaintUploader);
    hide(els.inpaintEditorWrap);
    if (els.inpaintFile) els.inpaintFile.value = "";
  }

  function readFileAsDataURL(file) {
    return new Promise((resolve, reject) => {
      if (file.size > 12 * 1024 * 1024) {
        reject(new Error("图片不能超过 12MB"));
        return;
      }
      const reader = new FileReader();
      reader.onload = (e) => resolve(e.target.result);
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
  }

  // ---- request / generate ----
  function buildRequestBody() {
    const safeInt = (v, d) => {
      const n = parseInt(v, 10);
      return Number.isNaN(n) ? d : n;
    };
    const safeFloat = (v, d) => {
      const n = parseFloat(v);
      return Number.isNaN(n) ? d : n;
    };

    const isInpaint = currentMode === "inpaint";
    const body = {
      mode: currentMode,
      nai_prompt: isInpaint
        ? (els.inpaintNaiPrompt.value || "").trim()
        : els.naiPrompt.value.trim(),
      nl_prompt: isInpaint
        ? (els.inpaintNlPrompt.value || "").trim()
        : els.nlPrompt.value.trim(),
      style: els.style.value,
      size: els.size.value,
      sampler: els.sampler.value,
      steps: safeInt(els.steps.value, 28),
      scale: safeFloat(els.scale.value, 5),
      noise_schedule: els.noiseSchedule.value,
      model: els.model.value,
      n: 1,
      seed: safeInt(els.seed.value, 0),
      quality: els.quality.checked,
      uc_preset: els.ucPreset.value,
      variety_boost: els.varietyBoost.checked,
      cfg_rescale: safeFloat(els.cfgRescale.value, 0),
    };
    const neg = els.negative.value.trim();
    if (neg) body.negative = neg;
    if (!isInpaint && body.style === "custom") {
      body.custom_artists = els.customArtists.value.trim();
    }
    if (isInpaint) {
      body.inpaint = {
        image: inpaint.imageDataUrl,
        mask: inpaint.maskDataUrl,
        strength: safeFloat(els.inpaintStrength.value, 1),
      };
      if (inpaint.sizeArray) body.size_array = inpaint.sizeArray;
      body._invert = !!(els.inpaintInvert && els.inpaintInvert.checked);
    }
    return body;
  }

  async function generate() {
    if (isGenerating) return;
    let body = buildRequestBody();

    if (!body.nai_prompt && !body.nl_prompt) {
      showError(
        currentMode === "inpaint"
          ? "请填写改图提示词（NAI 标签或自然语言）。"
          : "请至少填写一个提示词（NAI 标签或自然语言）。"
      );
      return;
    }
    if (currentMode === "inpaint") {
      if (!inpaint.imageDataUrl) {
        showError("请先上传原图。");
        return;
      }
      if (!inpaint.maskDataUrl || !inpaint.strokes.length) {
        showError("请先在图上涂抹需要重绘的区域（白色）。");
        return;
      }
      if (body._invert) {
        body.inpaint.mask = await invertMask(inpaint.maskDataUrl);
      }
      delete body._invert;
    }

    lastRequestBody = body;
    isGenerating = true;
    setLoading(true);
    hideError();
    hideResults();

    try {
      const bridge = await getBridge();
      const resp = await bridge.apiPost("studio/generate", body);

      let images;
      let mergeInfo;
      if (Array.isArray(resp)) {
        images = resp;
      } else if (resp && Array.isArray(resp.data)) {
        images = resp.data;
        mergeInfo = resp.merge_info;
      } else if (resp && resp.data && Array.isArray(resp.data.data)) {
        images = resp.data.data;
        mergeInfo = resp.data.merge_info;
      } else {
        images = resp;
        mergeInfo = (resp && resp.merge_info) || (resp && resp.data && resp.data.merge_info);
      }

      if (!images || !Array.isArray(images) || images.length === 0) {
        const errMsg =
          (resp && resp.message) ||
          (resp && resp.data && resp.data.message) ||
          JSON.stringify(resp).slice(0, 200);
        throw new Error(errMsg);
      }

      if (mergeInfo) displayMergeInfo(mergeInfo);
      displayResults(images, body);
    } catch (err) {
      showError(err && err.message ? err.message : String(err));
    } finally {
      isGenerating = false;
      setLoading(false);
    }
  }

  function setTraceExpanded(expanded) {
    traceExpanded = !!expanded;
    if (!els.mergeInfo) return;
    els.mergeInfo.classList.toggle("expanded", traceExpanded);
    if (traceExpanded) {
      show(els.mergeSteps);
      els.toggleTrace.textContent = "收起";
    } else {
      hide(els.mergeSteps);
      els.toggleTrace.textContent = "展开";
    }
  }

  function displayMergeInfo(info) {
    els.mergeSteps.innerHTML = "";
    const steps = [];
    if (info.mode) {
      steps.push({
        label: "模式",
        value: info.mode === "inpaint" ? "局部重绘" : "文生图",
      });
    }
    if (info.nai_prompt) steps.push({ label: "NAI 标签（原样）", value: info.nai_prompt });
    if (info.nl_prompt) steps.push({ label: "自然语言", value: info.nl_prompt });
    if (info.nl_prompt && info.translated_nl) {
      const same = info.translated_nl === info.nl_prompt;
      steps.push({
        label: same ? "转译（未改动 / 未配置）" : "转译结果",
        value: info.translated_nl,
      });
    }
    steps.push({ label: "最终 Prompt", value: info.full_prompt, highlight: true });

    steps.forEach((step, idx) => {
      const li = document.createElement("li");
      const n = document.createElement("span");
      n.className = "n";
      n.textContent = String(idx + 1);
      const body = document.createElement("div");
      const lbl = document.createElement("div");
      lbl.className = "lbl";
      lbl.textContent = step.label;
      const val = document.createElement("div");
      val.className = "val" + (step.highlight ? " hi" : "");
      val.textContent = step.value;
      body.appendChild(lbl);
      body.appendChild(val);
      li.appendChild(n);
      li.appendChild(body);
      els.mergeSteps.appendChild(li);
    });
    show(els.mergeInfo);
    setTraceExpanded(false);
  }

  function setLoading(loading) {
    if (loading) {
      hide(els.emptyState);
      hide(els.errorState);
      hide(els.resultWrap);
      hide(els.mergeInfo);
      show(els.loadingState);
      els.generateBtn.disabled = true;
      els.loadingText.textContent =
        currentMode === "inpaint" ? "局部重绘中…" : "转译并生成中…";
    } else {
      hide(els.loadingState);
      els.generateBtn.disabled = false;
    }
  }

  function showError(msg) {
    hide(els.emptyState);
    hide(els.loadingState);
    hide(els.resultWrap);
    hide(els.mergeInfo);
    show(els.errorState);
    els.errorMsg.textContent = msg || "未知错误";
  }
  function hideError() { hide(els.errorState); }
  function hideResults() {
    hide(els.resultWrap);
    hide(els.mergeInfo);
    show(els.emptyState);
    lastB64 = null;
  }

  function displayResults(images, requestBody) {
    hide(els.emptyState);
    hide(els.errorState);
    const item = images[0];
    const b64 = item.b64_json || item.b64 || item;
    lastB64 = b64;
    els.resultImage.src = "data:image/png;base64," + b64;
    const modeTag = requestBody.mode === "inpaint" ? "局部重绘" : (STYLE_LABELS[requestBody.style] || requestBody.style);
    els.resultMeta.textContent =
      modeTag +
      " · " +
      (requestBody.size_array
        ? requestBody.size_array.join("×")
        : requestBody.size || "") +
      " · " +
      (requestBody.model || "");
    show(els.resultWrap);
  }

  function openLightbox(src) {
    const lb = document.createElement("div");
    lb.className = "lightbox";
    const img = document.createElement("img");
    img.src = src;
    img.addEventListener("click", (e) => e.stopPropagation());
    lb.appendChild(img);
    lb.addEventListener("click", () => lb.remove());
    document.body.appendChild(lb);
  }

  function downloadImage() {
    if (!lastB64) return;
    const link = document.createElement("a");
    link.href = "data:image/png;base64," + lastB64;
    link.download = "studio_" + Date.now() + ".png";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }

  function resetParams() {
    els.naiPrompt.value = "";
    els.nlPrompt.value = "";
    if (els.inpaintNaiPrompt) els.inpaintNaiPrompt.value = "";
    if (els.inpaintNlPrompt) els.inpaintNlPrompt.value = "";
    els.sampler.value = "k_euler_ancestral";
    els.steps.value = "28";
    els.scale.value = "5";
    els.noiseSchedule.value = "karras";
    fillModelOptions(DEFAULT_MODELS, "nai-diffusion-4-5-full");
    els.seed.value = "0";
    els.quality.checked = true;
    els.ucPreset.value = "light";
    els.varietyBoost.checked = false;
    els.cfgRescale.value = "0";
    els.style.value = "vertical";
    syncSizeSeg("竖图");
    els.negative.value = "";
    els.customArtists.value = "";
    if (els.inpaintStrength) {
      els.inpaintStrength.value = "1";
      updateStrengthLabel();
    }
    if (els.inpaintInvert) els.inpaintInvert.checked = false;
    clearInpaintImage();
    document.querySelectorAll(".block[data-section]").forEach((block) => {
      const key = block.dataset.section;
      setSectionOpen(
        block,
        key === "prompt" ||
          key === "compose" ||
          key === "inpaint-source" ||
          key === "inpaint-prompt"
      );
    });
    toggleCustomArtists();
    setMode("txt2img");
    saveCache();
  }

  async function loadDefaultNegative() {
    try {
      const bridge = await getBridge();
      const resp = await bridge.apiGet("studio/config");
      const config = (resp && resp.data) ? resp.data : resp;
      if (config.default_negative) els.negative.value = config.default_negative;
      else fallbackDefaultNegative();
    } catch (e) {
      fallbackDefaultNegative();
    }
    saveCache();
  }

  function fallbackDefaultNegative() {
    els.negative.value =
      "{{bad anatomy}},{bad feet},bad hands,{{{bad proportions}}},{blurry},cloned face,cropped," +
      "{{{deformed}}},{{{disfigured}}},error,{{{extra arms}}},{extra digit},{{{extra legs}}},extra limbs," +
      "{{extra limbs}},{fewer digits},{{{fused fingers}}},gross proportions," +
      "jpeg artifacts,{{{{long neck}}}},low quality,{malformed limbs},{{missing arms}},{missing fingers}," +
      "{{missing legs}},mutated hands,{{{mutation}}},normal quality," +
      "{{poorly drawn face}},{{poorly drawn hands}},signature,text,{{too many fingers}}," +
      "{{{ugly}}},username,watermark,worst quality";
  }

  function bindEvents() {
    bindSections();

    // mode switch
    document.querySelectorAll(".mode-btn").forEach((btn) => {
      btn.addEventListener("click", () => setMode(btn.dataset.mode, true));
    });

    if (els.sizeSeg) {
      els.sizeSeg.querySelectorAll(".seg-item").forEach((btn) => {
        btn.addEventListener("click", () => {
          if (currentMode === "inpaint" && inpaint.imageDataUrl) return; // 有图时尺寸锁定
          syncSizeSeg(btn.dataset.value);
          saveCache();
        });
      });
    }

    els.style.addEventListener("change", toggleCustomArtists);
    els.generateBtn.addEventListener("click", generate);
    els.resetBtn.addEventListener("click", resetParams);
    els.retryBtn.addEventListener("click", () => {
      if (lastRequestBody) {
        hideError();
        generate();
      }
    });
    els.loadDefaultNegative.addEventListener("click", loadDefaultNegative);
    els.downloadBtn.addEventListener("click", downloadImage);
    els.resultImage.addEventListener("click", () => openLightbox(els.resultImage.src));
    els.toggleTrace.addEventListener("click", () => {
      setTraceExpanded(!traceExpanded);
      saveCache();
    });

    CACHE_FIELDS.forEach((key) => {
      const el = els[key];
      if (!el) return;
      el.addEventListener("input", saveCache);
      el.addEventListener("change", saveCache);
    });
    els.quality.addEventListener("change", saveCache);
    els.varietyBoost.addEventListener("change", saveCache);
    if (els.inpaintStrength) {
      els.inpaintStrength.addEventListener("input", () => {
        updateStrengthLabel();
        saveCache();
      });
    }
    if (els.inpaintInvert) els.inpaintInvert.addEventListener("change", saveCache);
    if (els.brushSize) {
      els.brushSize.addEventListener("input", () => {
        inpaint.brushSize = parseInt(els.brushSize.value, 10) || 30;
        updateBrushLabel();
        saveCache();
      });
    }

    // tools
    if (els.toolBrush) els.toolBrush.addEventListener("click", () => setTool("brush"));
    if (els.toolEraser) els.toolEraser.addEventListener("click", () => setTool("eraser"));
    if (els.toolLasso) els.toolLasso.addEventListener("click", () => setTool("lasso"));
    if (els.toolUndo) {
      els.toolUndo.addEventListener("click", () => {
        if (inpaint.strokes.length) {
          inpaint.strokes.pop();
          redrawInpaint();
          saveMask();
        }
      });
    }
    if (els.toolClear) {
      els.toolClear.addEventListener("click", () => {
        inpaint.strokes = [];
        redrawInpaint();
        saveMask();
      });
    }
    if (els.toolRemoveImage) {
      els.toolRemoveImage.addEventListener("click", clearInpaintImage);
    }

    // uploader
    if (els.inpaintUploader) {
      els.inpaintUploader.addEventListener("click", () => els.inpaintFile && els.inpaintFile.click());
      els.inpaintUploader.addEventListener("dragover", (e) => {
        e.preventDefault();
        els.inpaintUploader.classList.add("dragover");
      });
      els.inpaintUploader.addEventListener("dragleave", () => {
        els.inpaintUploader.classList.remove("dragover");
      });
      els.inpaintUploader.addEventListener("drop", async (e) => {
        e.preventDefault();
        els.inpaintUploader.classList.remove("dragover");
        const file = e.dataTransfer.files && e.dataTransfer.files[0];
        if (!file) return;
        try {
          const url = await readFileAsDataURL(file);
          await loadInpaintImage(url);
        } catch (err) {
          showError(err.message || String(err));
        }
      });
    }
    if (els.inpaintFile) {
      els.inpaintFile.addEventListener("change", async () => {
        const file = els.inpaintFile.files && els.inpaintFile.files[0];
        if (!file) return;
        try {
          const url = await readFileAsDataURL(file);
          await loadInpaintImage(url);
        } catch (err) {
          showError(err.message || String(err));
        }
      });
    }

    // canvas draw
    const canvas = els.inpaintCanvas;
    if (canvas) {
      canvas.addEventListener("mousedown", inpaintStart);
      canvas.addEventListener("mousemove", inpaintMove);
      canvas.addEventListener("mouseup", inpaintEnd);
      canvas.addEventListener("mouseleave", inpaintEnd);
      canvas.addEventListener("touchstart", (e) => { e.preventDefault(); inpaintStart(e); }, { passive: false });
      canvas.addEventListener("touchmove", (e) => { e.preventDefault(); inpaintMove(e); }, { passive: false });
      canvas.addEventListener("touchend", (e) => { e.preventDefault(); inpaintEnd(); }, { passive: false });
    }

    [els.naiPrompt, els.nlPrompt, els.inpaintNaiPrompt, els.inpaintNlPrompt]
      .filter(Boolean)
      .forEach((ta) => {
        ta.addEventListener("keydown", (e) => {
          if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
            e.preventDefault();
            generate();
          }
        });
      });
  }

  async function init() {
    bindEvents();
    updateBrushLabel();
    updateStrengthLabel();
    setTool("brush");
    setMode("txt2img", false);
    await loadCache();
    toggleCustomArtists();
    await loadConfigStatus();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
