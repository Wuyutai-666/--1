(() => {
  "use strict";

  /* ==========================================================
     常量与工具
     ========================================================== */

  const PALETTES = {
    spicy: ["#d93a2b", "#f2833a"],
    hotpot: ["#b71f2e", "#e85a3b"],
    charcoal: ["#3b2a1e", "#8a5a34"],
    teal: ["#0f6b5f", "#2fa08a"],
    jade: ["#1f7a55", "#57b07c"],
    sea: ["#1d5e7a", "#3e9eb5"],
    aqua: ["#166b7a", "#46a8a0"],
    clay: ["#6e4326", "#a97543"],
    wheat: ["#a86b1e", "#e0a33e"],
    orange: ["#b44a17", "#e8823b"],
    indigo: ["#3b3b78", "#6c6cb0"],
    rose: ["#a63a5a", "#d9738b"],
    olive: ["#5f5f25", "#9c9c4a"],
    green: ["#2e6b3f", "#5fae6b"],
    slate: ["#3a3a3f", "#6d6d74"],
  };

  const CATEGORY_PALETTE = {
    川菜: "spicy",
    湘菜: "spicy",
    火锅: "hotpot",
    烧烤: "charcoal",
    粤菜: "teal",
    苏菜: "jade",
    浙菜: "sea",
    闽菜: "aqua",
    徽菜: "clay",
    鲁菜: "wheat",
    东北菜: "orange",
    面食: "wheat",
    日料: "indigo",
    韩餐: "rose",
    西餐: "olive",
    轻食: "green",
  };

  const SPICY_CAP_LABELS = ["不辣", "微辣", "中辣", "重辣", "特辣", "不限"];
  const SPICY_DISH_LABELS = ["不辣", "微辣", "中辣", "重辣", "特辣", "爆辣"];
  const WEEKDAYS = "日一二三四五六";

  const REC_FILTERS = [
    { id: "all", label: "全部", params: "" },
    { id: "mild", label: "不辣", params: "&max_spicy=0" },
    { id: "budget", label: "¥30 内", params: "&max_price=30" },
    { id: "rating", label: "评分 4.6+", params: "&min_rating=4.6" },
  ];

  const EVENT_META = {
    click: { label: "点击", icon: "eye", weight: "+1", tone: "pos" },
    detail_view: { label: "查看详情", icon: "eye", weight: "+3", tone: "pos" },
    view_detail: { label: "查看详情", icon: "eye", weight: "+3", tone: "pos" },
    favorite: { label: "收藏", icon: "heart", weight: "+4", tone: "pos" },
    cart_add: { label: "加购", icon: "cart", weight: "+6", tone: "pos" },
    add_cart: { label: "加购", icon: "cart", weight: "+6", tone: "pos" },
    order: { label: "下单", icon: "check", weight: "+15", tone: "pos" },
    dismiss: { label: "忽略", icon: "ban", weight: "0", tone: "" },
    ignore: { label: "忽略", icon: "ban", weight: "0", tone: "" },
    not_interested: {
      label: "不感兴趣",
      icon: "ban",
      weight: "-10",
      tone: "neg",
    },
    disinterest: {
      label: "不感兴趣",
      icon: "ban",
      weight: "-10",
      tone: "neg",
    },
    rating: { label: "评分", icon: "star", weight: "按分值", tone: "" },
    rating_positive: {
      label: "评分",
      icon: "star",
      weight: "按分值",
      tone: "",
    },
    rating_negative: {
      label: "评分",
      icon: "star",
      weight: "按分值",
      tone: "",
    },
    search: { label: "搜索", icon: "search", weight: "", tone: "" },
  };

  const PREF_ROWS = [
    { key: "preferred_categories", label: "偏好菜系" },
    { key: "avoided_foods", label: "忌口菜品" },
    { key: "budget_max", label: "预算上限" },
    { key: "spicy_max", label: "辣度上限" },
    { key: "min_rating", label: "最低评分" },
    { key: "delivery_fee_max", label: "配送费上限" },
    { key: "notes", label: "备注" },
  ];

  const METRIC_META = [
    { key: "spicy_preference", label: "辣度偏好", icon: "flame", kind: "spicy" },
    { key: "price_preference", label: "价格带", icon: "wallet", kind: "price" },
    {
      key: "delivery_fee_preference",
      label: "配送费",
      icon: "bike",
      kind: "fee",
    },
    {
      key: "distance_preference",
      label: "距离",
      icon: "pin",
      kind: "distance",
    },
  ];

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) =>
    Array.from(root.querySelectorAll(selector));

  const view = $("#view");
  const modalRoot = $("#modalRoot");
  const cartRoot = $("#cartRoot");
  const toastRoot = $("#toastRoot");

  const state = {
    restaurants: [],
    categories: [],
    profile: null,
    menu: null,
    menuCategory: "全部",
    menuQuery: "",
    currentEpoi: "",
    recFilter: "all",
    cart: [],
    cartOpen: false,
    dishMap: new Map(),
    recordedSearches: new Set(),
    eventFilter: "behavior",
    chatBusy: false,
    chatSessionId: "",
    chatStatus: null,
    chatPhaseTimer: null,
    chatLoaded: false,
  };

  let dishSequence = 0;

  const esc = (value) =>
    String(value ?? "").replace(/[&<>"']/g, (character) => {
      const map = {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      };
      return map[character];
    });

  const icon = (name, className = "ic") =>
    `<svg class="${className}" aria-hidden="true"><use href="#i-${name}"/></svg>`;

  const money = (value) => {
    const number = Number(value || 0);
    return Number.isInteger(number) ? String(number) : number.toFixed(1);
  };

  const salesText = (value) => {
    const number = Number(value || 0);
    return number.toLocaleString("zh-CN");
  };

  const ratingText = (value) => {
    const number = Number(value || 0);
    return number > 0 ? number.toFixed(1) : "—";
  };

  const spicyCapLabel = (value) =>
    SPICY_CAP_LABELS[Math.max(0, Math.min(5, Number(value ?? 5)))];

  const spicyDishLabel = (value) =>
    SPICY_DISH_LABELS[Math.max(0, Math.min(5, Number(value || 0)))];

  const paletteOf = (category) =>
    PALETTES[CATEGORY_PALETTE[category] || "slate"] || PALETTES.slate;

  const coverVars = (category) => {
    const [start, end] = paletteOf(category);
    return `--c1:${start};--c2:${end}`;
  };

  const dotStyle = (category) => {
    const [start] = paletteOf(category);
    return `--dot:${start}`;
  };

  const charOf = (value) => {
    const text = String(value || "食").trim();
    return text ? Array.from(text)[0] : "食";
  };

  const parseTags = (value) => {
    if (Array.isArray(value)) return value.filter(Boolean);
    return String(value || "")
      .split(/[,，、]/)
      .map((item) => item.trim())
      .filter(Boolean);
  };

  const greeting = () => {
    const hour = new Date().getHours();
    if (hour < 5) return "夜深了";
    if (hour < 11) return "早上好";
    if (hour < 14) return "中午好";
    if (hour < 18) return "下午好";
    return "晚上好";
  };

  const parseDbDate = (value) => {
    const text = String(value || "").replace(" ", "T");
    if (!text) return new Date(NaN);
    const hasZone = /[zZ]$|[+-]\d{2}:?\d{2}$/.test(text);
    return new Date(hasZone ? text : `${text}Z`);
  };

  const relativeTime = (value) => {
    if (!value) return "";
    const date = parseDbDate(value);
    if (Number.isNaN(date.getTime())) return String(value);
    const diff = Date.now() - date.getTime();
    if (diff < 60 * 1000) return "刚刚";
    if (diff < 60 * 60 * 1000) return `${Math.floor(diff / 60000)} 分钟前`;
    if (diff < 24 * 60 * 60 * 1000) {
      return `${Math.floor(diff / 3600000)} 小时前`;
    }
    if (diff < 7 * 24 * 60 * 60 * 1000) {
      return `${Math.floor(diff / 86400000)} 天前`;
    }
    return `${date.getMonth() + 1} 月 ${date.getDate()} 日`;
  };

  const dateText = (value) => {
    const date = parseDbDate(value);
    if (Number.isNaN(date.getTime())) return String(value || "");
    return `${date.getMonth() + 1} 月 ${date.getDate()} 日`;
  };

  const clockText = (value) => {
    const date = value ? parseDbDate(value) : new Date();
    if (Number.isNaN(date.getTime())) return "";
    return `${String(date.getHours()).padStart(2, "0")}:${String(
      date.getMinutes()
    ).padStart(2, "0")}`;
  };

  const numberOrNull = (value) => {
    const text = String(value ?? "").trim();
    if (!text) return null;
    const number = Number(text);
    return Number.isFinite(number) ? number : null;
  };

  /* ==========================================================
     接口
     ========================================================== */

  async function api(path, options = {}) {
    const response = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    let data = null;
    try {
      data = await response.json();
    } catch (error) {
      data = null;
    }
    if (!response.ok) {
      const message =
        (data && (data.error || data.msg)) || `请求失败（${response.status}）`;
      throw new Error(message);
    }
    return data;
  }

  async function recordAction(action, dish, extra = {}) {
    const { silent = false, ...rest } = extra;
    try {
      return await api("/api/action", {
        method: "POST",
        body: JSON.stringify({
          action,
          dish_id: dish?.id || "",
          dish_name: dish?.name || "",
          e_poi_id: dish?.ePoiId || state.currentEpoi || "",
          ...rest,
        }),
      });
    } catch (error) {
      if (!silent) toast(error.message, "error");
      return null;
    }
  }

  function recordSearchOnce(query) {
    if (!query || state.recordedSearches.has(query)) return;
    state.recordedSearches.add(query);
    api("/api/action", {
      method: "POST",
      body: JSON.stringify({
        action: "search",
        query,
        e_poi_id: state.currentEpoi || "",
      }),
    }).catch(() => {});
  }

  /* ==========================================================
     Toast / 弹窗
     ========================================================== */

  function toast(message, tone = "default") {
    if (!message) return;
    const element = document.createElement("div");
    element.className = `toast ${tone === "error" ? "error" : ""}`.trim();
    element.innerHTML = `${icon(
      tone === "error" ? "info" : "check"
    )}<span>${esc(message)}</span>`;
    toastRoot.appendChild(element);
    window.setTimeout(() => {
      element.classList.add("out");
      window.setTimeout(() => element.remove(), 260);
    }, 2500);
  }

  function openModal(html) {
    modalRoot.innerHTML = html;
    document.body.classList.add("no-scroll");
  }

  function closeModal() {
    modalRoot.innerHTML = "";
    if (!state.cartOpen) {
      document.body.classList.remove("no-scroll");
    }
  }

  function emptyBlock({ iconName = "bowl", title, text, action = "" }) {
    return `<div class="empty">
      <div class="empty-art">${icon(iconName)}</div>
      <h3>${esc(title)}</h3>
      <p>${esc(text)}</p>
      ${action}
    </div>`;
  }

  /* ==========================================================
     菜品数据与卡片
     ========================================================== */

  function normalizeDish(raw, source) {
    const name = raw.name || raw.dish_name || "未命名菜品";
    return {
      key: `dish-${++dishSequence}`,
      source,
      id: raw.dish_id || raw.id || raw.e_dish_code || name,
      name,
      price: Number(raw.price || 0),
      spicy: Number(raw.spicy_level || 0),
      sales: Number(raw.month_sales || 0),
      tags: parseTags(raw.tags),
      description: raw.description || "",
      category:
        raw.category ||
        raw.category_name ||
        (state.menu && state.menu.restaurant.category) ||
        "",
      categoryName: raw.category_name || raw.category || "",
      restaurant: raw.restaurant_name || "",
      restaurantId: raw.restaurant_id || "",
      ePoiId: raw.e_poi_id || raw.ePoiId || state.currentEpoi || "",
      rating: raw.rating != null ? Number(raw.rating) : null,
      unit: raw.unit || "份",
      soldOut: Number(raw.is_sold_out || 0) === 1,
      score: raw.score != null ? Number(raw.score) : null,
      reasons: Array.isArray(raw.reasons) ? raw.reasons : [],
    };
  }

  function registerDish(raw, source) {
    const dish = normalizeDish(raw, source);
    state.dishMap.set(dish.key, dish);
    return dish.key;
  }

  function getDish(key) {
    return state.dishMap.get(key) || null;
  }

  function defaultDescription(dish) {
    if (dish.description) return dish.description;
    return `${dish.categoryName || dish.category || "本店"}风味 · 现点现做`;
  }

  function spicyTag(dish) {
    if (!dish.spicy) {
      return `<span class="tag">不辣</span>`;
    }
    return `<span class="tag spicy">${icon("flame")} ${spicyDishLabel(
      dish.spicy
    )}</span>`;
  }

  function dishCard(raw, options = {}) {
    const dish = normalizeDish(raw, options.source || "menu");
    state.dishMap.set(dish.key, dish);
    const key = dish.key;
    const showStore = Boolean(options.showStore);
    const tags = dressTags(dish);
    return `<article class="dish-card" data-open-dish="${key}" style="${coverVars(
      dish.category
    )}">
      <div class="dish-thumb">
        <span class="char">${esc(charOf(dish.name))}</span>
        <span class="seal">${esc(dish.categoryName || dish.category || "招牌")}</span>
        ${dish.soldOut ? '<span class="sold-out">已售罄</span>' : ""}
      </div>
      <div class="dish-main">
        <div class="dish-head">
          <h3>${esc(dish.name)}</h3>
          <span class="price">¥${money(dish.price)}</span>
        </div>
        <p class="dish-desc">${esc(defaultDescription(dish))}</p>
        <div class="dish-tags">${tags}</div>
        <div class="dish-meta">
          <span>${icon("flame")}月售 ${salesText(dish.sales)}</span>
          ${
            showStore && dish.restaurant
              ? `<span>${icon("store")}${esc(dish.restaurant)}</span>`
              : ""
          }
        </div>
        <div class="dish-actions">
          <button class="icon-btn" title="收藏" aria-label="收藏" data-action="favorite" data-key="${key}">${icon(
      "heart"
    )}</button>
          <button class="icon-btn" title="查看详情" aria-label="查看详情" data-action="detail" data-key="${key}">${icon(
      "eye"
    )}</button>
          <button class="icon-btn danger" title="不感兴趣" aria-label="不感兴趣" data-action="not-interested" data-key="${key}">${icon(
      "ban"
    )}</button>
          <span class="spacer"></span>
          <button class="btn btn-ghost btn-sm" data-action="add-cart" data-key="${key}" ${
      dish.soldOut ? "disabled" : ""
    }>${icon("plus")}加购</button>
          <button class="btn btn-primary btn-sm" data-action="order" data-key="${key}" ${
      dish.soldOut ? "disabled" : ""
    }>下单</button>
        </div>
      </div>
    </article>`;
  }

  function dressTags(dish) {
    const spicyLabels = new Set(SPICY_DISH_LABELS);
    const tags = [spicyTag(dish)];
    dish.tags
      .filter((tag) => !spicyLabels.has(tag))
      .slice(0, 3)
      .forEach((tag, index) => {
        tags.push(
          `<span class="tag ${index === 0 ? "hot" : ""}">${esc(tag)}</span>`
        );
      });
    return tags.join("");
  }

  function recCard(item) {
    const key = registerDish(item, "recommend");
    const reasons = (item.reasons || [])
      .slice(0, 3)
      .map(
        (reason, index) =>
          `<span class="reason ${index === 0 ? "hot" : ""}">${esc(
            reason
          )}</span>`
      )
      .join("");
    return `<article class="rec-card" data-open-dish="${key}" style="${coverVars(
      item.category
    )}">
      <div class="rec-art">
        <div class="rec-top">
          <span class="rank-badge">TOP ${String(item.rank || 0).padStart(
            2,
            "0"
          )}</span>
          <span class="score-badge">${Math.round(
            Number(item.score || 0)
          )}<small>匹配</small></span>
        </div>
        <span class="rec-char">${esc(charOf(item.category))}</span>
      </div>
      <div class="rec-body">
        <div class="rec-title">
          <h3>${esc(item.dish_name)}</h3>
          <span class="rec-price">¥${money(item.price)}</span>
        </div>
        <div class="rec-store">${icon("store")}${esc(
      item.restaurant_name || ""
    )} · ${esc(item.category || "")}</div>
        <div class="rec-reasons">${reasons || `<span class="reason">多维度得分均衡</span>`}</div>
        <div class="rec-foot">
          <div class="meta">
            <span>${icon("flame")}月售 ${salesText(item.month_sales)}</span>
            <span>${icon("star")}${ratingText(item.rating)}</span>
          </div>
          <button class="btn btn-brand btn-sm" data-action="add-cart" data-key="${key}">加购</button>
        </div>
      </div>
    </article>`;
  }

  function storeCard(store) {
    const open =
      store.is_open === true
        ? '<span class="badge open">营业中</span>'
        : store.is_open === false
        ? '<span class="badge closed">休息中</span>'
        : "";
    return `<article class="store-card" data-open-store="${esc(
      store.e_poi_id
    )}" style="${coverVars(store.category)}">
      <div class="store-cover">
        <div class="store-badges">
          <span class="badge rating">${icon("star", "ic fill")}${ratingText(
      store.rating
    )}</span>
          ${open}
          <span class="badge">${esc(store.category || "其他")}</span>
        </div>
        <span class="store-char">${esc(charOf(store.category))}</span>
      </div>
      <div class="store-body">
        <h3>${esc(store.name)}</h3>
        <div class="store-sub">${icon("clock")}${esc(
      store.business_hours || "营业时间未知"
    )}</div>
        <div class="store-meta">
          <span>${icon("bike")}配送 ¥${money(store.delivery_fee)}</span>
          <span>起送 ¥${money(store.min_order)}</span>
          <span>${store.dish_count} 道菜</span>
        </div>
        <div class="store-foot">
          <span class="deal">距离 ${Number(store.distance_km || 0).toFixed(
            1
          )} km</span>
          <span class="go-btn">进店看看 ${icon("arrow-right")}</span>
        </div>
      </div>
    </article>`;
  }

  /* ==========================================================
     购物车
     ========================================================== */

  const cartCount = () =>
    state.cart.reduce((total, item) => total + item.qty, 0);

  const cartTotal = () =>
    state.cart.reduce((total, item) => total + item.price * item.qty, 0);

  function addToCart(dish) {
    if (!dish) return;
    if (dish.soldOut) {
      toast("这道菜暂时售罄", "error");
      return;
    }
    const storeId = dish.ePoiId || state.currentEpoi || "unknown";
    if (state.cart.length && state.cart[0].ePoiId !== storeId) {
      state.cart = [];
      toast(`已切换到「${dish.restaurant || "新商家"}」的购物车`);
    }
    const key = `${storeId}:${dish.id}`;
    const existing = state.cart.find((item) => item.key === key);
    if (existing) {
      existing.qty += 1;
    } else {
      state.cart.push({
        key,
        id: dish.id,
        name: dish.name,
        price: dish.price,
        qty: 1,
        ePoiId: storeId,
        restaurant: dish.restaurant || "本店",
        category: dish.category,
      });
    }
    renderCart();
    toast(`已加入购物车「${dish.name}」 · 画像 +6`);
    recordAction("cart_add", dish, { silent: true });
  }

  function changeCartQty(key, delta) {
    const item = state.cart.find((entry) => entry.key === key);
    if (!item) return;
    item.qty += delta;
    if (item.qty <= 0) {
      state.cart = state.cart.filter((entry) => entry.key !== key);
    }
    if (!state.cart.length) state.cartOpen = false;
    renderCart();
  }

  function removeCartItem(key) {
    state.cart = state.cart.filter((entry) => entry.key !== key);
    if (!state.cart.length) state.cartOpen = false;
    renderCart();
  }

  function openCart() {
    if (!state.cart.length) {
      toast("购物车还是空的，先去挑一道菜");
      return;
    }
    state.cartOpen = true;
    renderCart();
  }

  function closeCart() {
    state.cartOpen = false;
    document.body.classList.remove("no-scroll");
    renderCart();
  }

  function cartItemsHtml() {
    return state.cart
      .map(
        (item) => `<div class="cart-item" style="${coverVars(item.category)}">
          <div class="cart-item-art">${esc(charOf(item.name))}</div>
          <div class="cart-item-info">
            <h3>${esc(item.name)}</h3>
            <p>${esc(item.restaurant)} · ¥${money(item.price)}</p>
          </div>
          <div class="cart-item-side">
            <span class="amount">¥${money(item.price * item.qty)}</span>
            <div class="qty">
              <button class="qty-btn" data-action="cart-dec" data-key="${esc(
                item.key
              )}" aria-label="减少">${icon("minus")}</button>
              <span>${item.qty}</span>
              <button class="qty-btn" data-action="cart-inc" data-key="${esc(
                item.key
              )}" aria-label="增加">${icon("plus")}</button>
            </div>
          </div>
        </div>`
      )
      .join("");
  }

  function renderCart() {
    if (!state.cart.length) {
      cartRoot.innerHTML = "";
      document.body.classList.remove("no-scroll");
      updateCartBadges();
      return;
    }
    const count = cartCount();
    const total = cartTotal();
    const restaurant = state.cart[0].restaurant;
    const drawer = state.cartOpen
      ? `<div class="drawer-backdrop" data-action="cart-close"></div>
        <aside class="cart-drawer" aria-label="购物车">
          <div class="drawer-head">
            <div>
              <h2>${icon("cart")}购物车 <span class="sub">${esc(
          restaurant
        )}</span></h2>
            </div>
            <button class="icon-btn" data-action="cart-close" aria-label="关闭购物车">${icon(
              "close"
            )}</button>
          </div>
          <div class="drawer-body">
            ${cartItemsHtml()}
          </div>
          <div class="drawer-foot">
            <div class="cart-total-row"><span>合计 · ${count} 件</span><strong>¥${money(
          total
        )}</strong></div>
            <button class="btn btn-primary btn-block" data-action="checkout">提交订单 ${icon(
              "arrow-right"
            )}</button>
            <div class="hint">下单会写入订单记录与行为画像</div>
          </div>
        </aside>`
      : "";
    cartRoot.innerHTML = `<button class="cart-fab" data-action="cart-open" aria-label="打开购物车">
        ${icon("cart")}<span>购物车</span><b class="cart-count">${count}</b><span class="cart-total">¥${money(
      total
    )}</span>
      </button>${drawer}`;
    document.body.classList.toggle("no-scroll", state.cartOpen);
    updateCartBadges();
  }

  function updateCartBadges() {
    const count = cartCount();
    $$("[data-cart-count]").forEach((element) => {
      element.textContent = count;
    });
  }

  async function checkout() {
    if (!state.cart.length) return;
    const items = [...state.cart];
    const total = cartTotal();
    const button = $('[data-action="checkout"]');
    if (button) {
      button.disabled = true;
      button.textContent = "提交中…";
    }
    try {
      for (const item of items) {
        await api("/api/action", {
          method: "POST",
          body: JSON.stringify({
            action: "order",
            dish_name: item.name,
            dish_id: item.id,
            e_poi_id: item.ePoiId,
          }),
        });
      }
      state.cart = [];
      state.cartOpen = false;
      renderCart();
      toast(`下单成功 · ${items.length} 道菜 · ¥${money(total)}`);
    } catch (error) {
      toast(error.message, "error");
      if (button) {
        button.disabled = false;
        button.textContent = "提交订单";
      }
    }
  }

  /* ==========================================================
     菜品详情弹窗
     ========================================================== */

  function openDishModal(dish) {
    if (!dish) return;
    const reasons = dish.reasons.length
      ? `<div class="rec-reasons" style="margin-top:14px">${dish.reasons
          .map((reason) => `<span class="reason">${esc(reason)}</span>`)
          .join("")}</div>`
      : "";
    const tags = dish.tags.length
      ? `<div class="dish-tags" style="margin-top:10px">${dressTags(dish)}</div>`
      : "";
    const storeLink = dish.ePoiId
      ? `<a class="btn btn-ghost btn-sm" href="/menu?ePoiId=${encodeURIComponent(
          dish.ePoiId
        )}" data-link>${icon("store")}进店</a>`
      : "";
    openModal(`<div class="modal-backdrop" data-close-modal>
      <div class="modal" role="dialog" aria-modal="true" aria-label="${esc(
        dish.name
      )}">
        <div class="dish-modal-hero" style="${coverVars(dish.category)}">
          <span class="dish-modal-art">${esc(charOf(dish.name))}</span>
          <div class="dish-modal-title">
            <h2>${esc(dish.name)}</h2>
            <div class="store">${icon("store")}${esc(
      dish.restaurant || "本店"
    )}</div>
            <div class="price">¥${money(dish.price)}<small> / ${
      esc(dish.unit) || "份"
    }</small></div>
          </div>
          <button class="icon-btn" data-action="modal-close" aria-label="关闭" style="color:#fff">${icon(
            "close"
          )}</button>
        </div>
        <div class="modal-body">
          <div class="dish-facts">
            <div class="fact"><span>月售</span><strong>${salesText(
              dish.sales
            )} 份</strong></div>
            <div class="fact"><span>辣度</span><strong>${spicyDishLabel(
              dish.spicy
            )}</strong></div>
            <div class="fact"><span>商家评分</span><strong>${ratingText(
              dish.rating
            )}</strong></div>
          </div>
          ${reasons}
          <p class="dish-modal-desc">${esc(defaultDescription(dish))}</p>
          ${tags}
          <div class="dish-modal-actions">
            <div class="stars" aria-label="为这道菜评分">
              ${[1, 2, 3, 4, 5]
                .map(
                  (value) =>
                    `<button class="star-btn" data-action="rate" data-value="${value}" data-key="${dish.key}" aria-label="${value} 分">${icon(
                      "star"
                    )}</button>`
                )
                .join("")}
            </div>
            <span class="spacer"></span>
            <button class="btn btn-ghost btn-sm" data-action="favorite" data-key="${
              dish.key
            }">${icon("heart")}收藏</button>
            <button class="btn btn-ghost btn-sm" data-action="not-interested" data-key="${
              dish.key
            }">不感兴趣</button>
            ${storeLink}
            <button class="btn btn-brand btn-sm" data-action="add-cart" data-key="${
              dish.key
            }">加购</button>
            <button class="btn btn-primary btn-sm" data-action="order" data-key="${
              dish.key
            }">下单</button>
          </div>
        </div>
      </div>
    </div>`);
  }

  async function luckyPick() {
    try {
      const data = await api("/api/recommendations?limit=20");
      const pool = (data.recommendations || []).slice(0, 10);
      if (!pool.length) {
        toast("暂时没有可推荐的菜品", "error");
        return;
      }
      const pick = pool[Math.floor(Math.random() * pool.length)];
      const key = registerDish(pick, "lucky");
      openDishModal(getDish(key));
      toast(`今天就吃「${pick.dish_name}」吧`);
    } catch (error) {
      toast(error.message, "error");
    }
  }

  /* ==========================================================
     通用组件
     ========================================================== */

  function topbar(stats) {
    const now = new Date();
    const weekday = WEEKDAYS[now.getDay()];
    const open = stats?.open_now ?? 0;
    return `<div class="topbar">
      <div class="greeting">
        <div class="eyebrow"><i class="dot"></i>${greeting()} · ${
      now.getMonth() + 1
    } 月 ${now.getDate()} 日 周${weekday}</div>
        <h1>今天想吃点什么？</h1>
      </div>
      <div class="top-actions">
        <span class="date-chip"><i class="live-dot"></i>${open} 家营业中</span>
        <a class="avatar" href="/profile" data-link title="default 用户">食</a>
      </div>
    </div>`;
  }

  function hero(profile, stats, topPick) {
    const summary = profile?.summary || {};
    const features = summary.feature_count || 0;
    const events = profile?.stats?.events || 0;
    const chips = ["川菜", "面食", "轻食", "火锅", "日料"]
      .map(
        (term) =>
          `<button class="hero-chip" data-action="search-term" data-q="${term}">${term}</button>`
      )
      .join("");
    const pickKey = topPick ? registerDish(topPick, "hero") : "";
    const plate = topPick
      ? `<div class="hero-art" ${
          pickKey ? `data-open-dish="${pickKey}" role="button" tabindex="0"` : ""
        } aria-label="查看今日灵感">
          <div class="hero-plate">
            <span class="plate-char">${esc(charOf(topPick.category))}</span>
            <div class="plate-chip">
              <small>今日灵感 · ${esc(topPick.category || "推荐")}</small>
              <strong>${esc(topPick.dish_name)}</strong>
              <span>${esc(topPick.restaurant_name || "")} · ¥${money(
          topPick.price
        )}</span>
            </div>
          </div>
        </div>`
      : "";
    return `<section class="hero">
      <div class="hero-inner">
        <div class="hero-eyebrow">${icon("sparkles")}FAN DIAN · 懂你的口味</div>
        <h2>今天这顿，<br>交给<em>口味画像</em>。</h2>
        <p>已经根据 <strong>${features} 条口味特征</strong>和 <strong>${events} 次真实行为</strong>，从 ${
      stats.restaurants
    } 家商家里挑好菜。预算、辣度、忌口都会实时参与计算。</p>
        <form class="hero-search" data-search-form>
          <svg class="ic"><use href="#i-search"/></svg>
          <input name="q" placeholder="搜索菜品、菜系或商家，例如「水煮鱼」" autocomplete="off" aria-label="搜索菜品、菜系或商家">
          <button class="btn btn-brand" type="submit">${icon(
            "search"
          )}<span>搜索</span></button>
        </form>
        <div class="hero-chips">
          <span class="label">灵感</span>
          ${chips}
          <button class="hero-chip lucky" data-action="lucky">${icon(
            "dice"
          )}帮我选一顿</button>
        </div>
      </div>
      ${plate}
    </section>`;
  }

  function statRow(stats, profile) {
    const features = profile?.summary?.feature_count || 0;
    const cards = [
      { icon: "store", value: stats.restaurants, label: "家商家" },
      { icon: "bowl", value: stats.dishes, label: "道菜品" },
      { icon: "grid", value: stats.categories, label: "个菜系" },
      { icon: "sparkles", value: features, label: "维口味特征" },
    ];
    return `<div class="stat-row">${cards
      .map(
        (card) => `<div class="stat">
          <span class="stat-icon">${icon(card.icon)}</span>
          <div><strong>${card.value}</strong><span>${card.label}</span></div>
        </div>`
      )
      .join("")}</div>`;
  }

  function segmentedFilters() {
    return `<div class="segmented">${REC_FILTERS.map(
      (filter) =>
        `<button data-action="rec-filter" data-filter="${filter.id}" class="${
          state.recFilter === filter.id ? "active" : ""
        }">${filter.label}</button>`
    ).join("")}</div>`;
  }

  function recSection(items) {
    const rail =
      items.length > 0
        ? items.map(recCard).join("")
        : `<div class="empty" style="min-width:min(620px,100%)">
            <div class="empty-art">${icon("search")}</div>
            <h3>这个条件下暂时没有合适的菜</h3>
            <p>试试放宽预算或辣度，画像会重新为你排序。</p>
          </div>`;
    return `<section class="section">
      <div class="section-head">
        <div class="section-title">
          <h2>为你推荐</h2>
          <span class="hint">${icon("sparkles")}多因子画像加权 · 实时计算</span>
        </div>
        <div class="right">
          ${segmentedFilters()}
          <div class="rail-nav">
            <button data-action="rail-scroll" data-dir="-1" aria-label="向左滚动">${icon(
              "arrow-left"
            )}</button>
            <button data-action="rail-scroll" data-dir="1" aria-label="向右滚动">${icon(
              "arrow-right"
            )}</button>
          </div>
        </div>
      </div>
      <div class="rail-wrap"><div class="rail" id="recRail">${rail}</div></div>
    </section>`;
  }

  async function applyRecFilter(filterId) {
    state.recFilter = filterId;
    $$('[data-action="rec-filter"]').forEach((button) => {
      button.classList.toggle("active", button.dataset.filter === filterId);
    });
    const rail = $("#recRail");
    if (!rail) return;
    rail.innerHTML = Array.from(
      { length: 4 },
      () => '<div class="skeleton" style="height:326px;border-radius:22px"></div>'
    ).join("");
    const filter = REC_FILTERS.find((item) => item.id === filterId);
    try {
      const data = await api(
        `/api/recommendations?limit=8${filter ? filter.params : ""}`
      );
      const items = data.recommendations || [];
      rail.innerHTML = items.length
        ? items.map(recCard).join("")
        : `<div class="empty" style="min-width:min(620px,100%)"><div class="empty-art">${icon(
            "search"
          )}</div><h3>这个条件下暂时没有合适的菜</h3><p>换个筛选条件试试。</p></div>`;
    } catch (error) {
      rail.innerHTML = `<div class="empty" style="min-width:min(620px,100%)"><div class="empty-art">${icon(
        "info"
      )}</div><h3>推荐加载失败</h3><p>${esc(error.message)}</p></div>`;
    }
  }

  function skeletonFor(kind) {
    if (kind === "menu") {
      return `<div class="skeleton skel-head"></div>
        <div class="skeleton skel-hero" style="height:190px"></div>
        <div class="skeleton" style="height:52px;margin-top:22px;border-radius:16px"></div>
        <div class="skel-grid">${"<div></div>".repeat(4)}</div>`;
    }
    return `<div class="skeleton skel-head"></div>
      <div class="skeleton skel-hero"></div>
      <div class="skel-row">${"<div></div>".repeat(4)}</div>
      <div class="skel-grid">${"<div></div>".repeat(4)}</div>`;
  }

  /* ==========================================================
     页面：AI 对话
     ========================================================== */

  const CHAT_SUGGESTIONS = [
    "数据库里一共有多少家餐厅？",
    "推荐一份 30 元以内的不辣午餐",
    "评分最高的 3 家餐厅是哪几家？",
    "我想吃川菜，有什么推荐？",
  ];

  const CHAT_PHASES = [
    "正在理解问题",
    "正在查询数据库",
    "正在整理结果",
    "正在生成回答",
  ];

  function renderMarkdown(source) {
    const raw = String(source || "").replace(/\r\n?/g, "\n").trim();
    if (!raw) return "";

    const inline = (text) => {
      let html = esc(text);
      html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
      html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
      html = html.replace(
        /\[([^\]]+)\]\((https?:\/\/[^)\s]+|\/[^)\s]*)\)/g,
        (match, label, url) => {
          let href = url.replace(/&amp;/g, "&");
          const internalMatch = href.match(
            /^https?:\/\/(?:127\.0\.0\.1|localhost):18080(\/.*)?$/
          );
          if (internalMatch) href = internalMatch[1] || "/";
          const internal = href.startsWith("/");
          const attrs = internal
            ? ' data-link="1"'
            : ' target="_blank" rel="noopener"';
          return `<a href="${esc(href)}"${attrs}>${label}</a>`;
        }
      );
      return html;
    };

    const lines = raw.split("\n");
    const out = [];
    let index = 0;
    let paragraph = [];

    const flushParagraph = () => {
      if (!paragraph.length) return;
      out.push(`<p>${paragraph.map(inline).join("<br>")}</p>`);
      paragraph = [];
    };

    while (index < lines.length) {
      const line = lines[index];

      if (!line.trim()) {
        flushParagraph();
        index += 1;
        continue;
      }

      if (line.trim().startsWith("```")) {
        flushParagraph();
        const code = [];
        index += 1;
        while (
          index < lines.length &&
          !lines[index].trim().startsWith("```")
        ) {
          code.push(lines[index]);
          index += 1;
        }
        index += 1;
        out.push(`<pre><code>${esc(code.join("\n"))}</code></pre>`);
        continue;
      }

      if (
        /^\s*\|.+\|\s*$/.test(line) &&
        index + 1 < lines.length &&
        /^\s*\|[\s:|-]+\|\s*$/.test(lines[index + 1])
      ) {
        flushParagraph();
        const parseRow = (row) =>
          row
            .trim()
            .replace(/^\|/, "")
            .replace(/\|$/, "")
            .split("|")
            .map((cell) => cell.trim());
        const headers = parseRow(line);
        index += 2;
        const rows = [];
        while (
          index < lines.length &&
          /^\s*\|.+\|\s*$/.test(lines[index])
        ) {
          rows.push(parseRow(lines[index]));
          index += 1;
        }
        out.push(
          `<div class="md-table"><table><thead><tr>${headers
            .map((header) => `<th>${inline(header)}</th>`)
            .join("")}</tr></thead><tbody>${rows
            .map(
              (row) =>
                `<tr>${headers
                  .map((_, cellIndex) => `<td>${inline(row[cellIndex] || "")}</td>`)
                  .join("")}</tr>`
            )
            .join("")}</tbody></table></div>`
        );
        continue;
      }

      const heading = line.match(/^(#{1,3})\s+(.*)$/);
      if (heading) {
        flushParagraph();
        const level = heading[1].length;
        out.push(`<h${level}>${inline(heading[2])}</h${level}>`);
        index += 1;
        continue;
      }

      const listMatch = line.match(/^\s*(?:([-*])|(\d+)\.)\s+(.*)$/);
      if (listMatch) {
        flushParagraph();
        const ordered = Boolean(listMatch[2]);
        const items = [];
        while (index < lines.length) {
          const itemMatch = lines[index].match(
            /^\s*(?:([-*])|(\d+)\.)\s+(.*)$/
          );
          if (!itemMatch) break;
          items.push(itemMatch[3]);
          index += 1;
        }
        const tag = ordered ? "ol" : "ul";
        out.push(
          `<${tag}>${items
            .map((item) => `<li>${inline(item)}</li>`)
            .join("")}</${tag}>`
        );
        continue;
      }

      if (line.trim().startsWith(">")) {
        flushParagraph();
        out.push(
          `<blockquote>${inline(
            line.replace(/^\s*>\s?/, "")
          )}</blockquote>`
        );
        index += 1;
        continue;
      }

      if (/^\s*([-*_])\1{2,}\s*$/.test(line)) {
        flushParagraph();
        out.push("<hr>");
        index += 1;
        continue;
      }

      paragraph.push(line);
      index += 1;
    }

    flushParagraph();
    return out.join("");
  }

  function getChatSessionId() {
    if (state.chatSessionId) return state.chatSessionId;
    let sessionId = "";
    try {
      sessionId = localStorage.getItem("fandian_chat_session") || "";
    } catch (error) {
      sessionId = "";
    }
    if (!sessionId) {
      sessionId = `web-${Date.now().toString(36)}-${Math.random()
        .toString(36)
        .slice(2, 8)}`;
      try {
        localStorage.setItem("fandian_chat_session", sessionId);
      } catch (error) {
        // localStorage may be unavailable; keep the in-memory id.
      }
    }
    state.chatSessionId = sessionId;
    return sessionId;
  }

  function newChatSession() {
    const sessionId = `web-${Date.now().toString(36)}-${Math.random()
      .toString(36)
      .slice(2, 8)}`;
    state.chatSessionId = sessionId;
    try {
      localStorage.setItem("fandian_chat_session", sessionId);
    } catch (error) {
      // Ignore storage errors.
    }
    return sessionId;
  }

  function chatStatusHtml() {
    const status = state.chatStatus;
    if (!status) {
      return `<span class="chat-status is-loading" id="chatStatus">连接中…</span>`;
    }
    if (status.ready) {
      return `<span class="chat-status ready" id="chatStatus">${icon(
        "check"
      )}模型已就绪</span>`;
    }
    return `<span class="chat-status off" id="chatStatus">${icon(
      "info"
    )}${status.ollama ? "模型未就绪" : "Ollama 未启动"}</span>`;
  }

  function chatWelcomeHtml() {
    return `<div class="chat-welcome">
      <div class="chat-welcome-mark">${icon("sparkles")}</div>
      <h3>你好，我是饭点 AI 助手</h3>
      <p>可以帮你查数据库、按预算和辣度筛选、修改口味偏好，也能根据画像推荐今天吃什么。</p>
      <div class="chat-suggestions">
        ${CHAT_SUGGESTIONS.map(
          (question) =>
            `<button class="chat-suggest" data-action="chat-suggest" data-q="${esc(
              question
            )}">${esc(question)}</button>`
        ).join("")}
      </div>
    </div>`;
  }

  function chatMessageHtml(role, content, createdAt = "") {
    const isUser = role === "user";
    const body = isUser
      ? `<p class="chat-plain">${esc(content).replace(/\n/g, "<br>")}</p>`
      : `<div class="md">${renderMarkdown(content)}</div>`;
    return `<div class="chat-msg ${isUser ? "user" : "ai"}">
      <div class="chat-msg-avatar">${isUser ? "我" : "AI"}</div>
      <div class="chat-bubble">
        ${body}
        <div class="chat-msg-meta">${
          isUser ? "你" : "饭点 AI"
        } · ${clockText(createdAt || null)}</div>
      </div>
    </div>`;
  }

  function scrollChat() {
    const container = $("#chatMessages");
    if (container) container.scrollTop = container.scrollHeight;
  }

  function appendChatMessage(role, content, createdAt = "") {
    const container = $("#chatMessages");
    if (!container) return;
    container.insertAdjacentHTML(
      "beforeend",
      chatMessageHtml(role, content, createdAt)
    );
    scrollChat();
  }

  function appendChatTyping() {
    const container = $("#chatMessages");
    if (!container) return;
    container.insertAdjacentHTML(
      "beforeend",
      `<div class="chat-msg ai" id="chatTyping">
        <div class="chat-msg-avatar">AI</div>
        <div class="chat-bubble chat-typing-bubble">
          <span class="chat-typing-dots"><i></i><i></i><i></i></span>
          <span id="chatPhase">正在理解问题</span>
        </div>
      </div>`
    );
    scrollChat();
    let phaseIndex = 0;
    window.clearInterval(state.chatPhaseTimer);
    state.chatPhaseTimer = window.setInterval(() => {
      phaseIndex = (phaseIndex + 1) % CHAT_PHASES.length;
      const phase = $("#chatPhase");
      if (phase) phase.textContent = CHAT_PHASES[phaseIndex];
    }, 2400);
  }

  function removeChatTyping() {
    window.clearInterval(state.chatPhaseTimer);
    state.chatPhaseTimer = null;
    const typing = $("#chatTyping");
    if (typing) typing.remove();
  }

  function appendChatError(message) {
    const container = $("#chatMessages");
    if (!container) return;
    container.insertAdjacentHTML(
      "beforeend",
      `<div class="chat-msg ai">
        <div class="chat-msg-avatar">!</div>
        <div class="chat-bubble chat-error">
          <strong>这次没有回答成功</strong>
          <p>${esc(message)}</p>
          <p class="chat-error-hint">先双击“查看AI状态.bat”确认 Ollama 与模型正常，再重试。</p>
        </div>
      </div>`
    );
    scrollChat();
  }

  function renderChatHistory(messages) {
    const container = $("#chatMessages");
    if (!container) return;
    container.innerHTML = "";
    if (!messages || !messages.length) {
      container.innerHTML = chatWelcomeHtml();
    } else {
      messages.forEach((message) => {
        container.insertAdjacentHTML(
          "beforeend",
          chatMessageHtml(
            message.role,
            message.content,
            message.created_at || ""
          )
        );
      });
    }
    if (state.chatStatus && !state.chatStatus.ready) {
      container.insertAdjacentHTML(
        "afterbegin",
        `<div class="chat-alert">
          ${icon("info")}
          <span>AI 后端还没有就绪，请先双击“启动AI后端.bat”，然后点这里重新检查。</span>
          <button class="btn btn-ghost btn-sm" data-action="chat-check">重新检查</button>
        </div>`
      );
    }
    scrollChat();
  }

  async function refreshChatStatus() {
    try {
      state.chatStatus = await api("/api/chat/status");
    } catch (error) {
      state.chatStatus = { ollama: false, ready: false, models: [] };
    }
    const current = $("#chatStatus");
    if (current) {
      const wrapper = document.createElement("span");
      wrapper.innerHTML = chatStatusHtml();
      current.replaceWith(wrapper.firstElementChild);
    }
    if (state.chatStatus.ready) {
      const alert = $(".chat-alert");
      if (alert) alert.remove();
    }
    return state.chatStatus;
  }

  async function sendChatMessage(rawMessage) {
    const message = String(rawMessage || "").trim();
    if (!message) {
      toast("先输入一个问题");
      return;
    }
    if (state.chatBusy) {
      toast("正在回答上一个问题，请稍等");
      return;
    }
    const input = $("#chatInput");
    const sendButton = $("#chatSend");
    state.chatBusy = true;
    if (input) input.value = "";
    if (sendButton) sendButton.disabled = true;
    const welcome = $(".chat-welcome");
    if (welcome) welcome.remove();
    appendChatMessage("user", message);
    appendChatTyping();

    try {
      const data = await api("/api/chat", {
        method: "POST",
        body: JSON.stringify({
          message,
          session_id: getChatSessionId(),
        }),
      });
      removeChatTyping();
      appendChatMessage("assistant", data.answer);
    } catch (error) {
      removeChatTyping();
      appendChatError(error.message);
      toast(error.message, "error");
    } finally {
      state.chatBusy = false;
      if (sendButton) sendButton.disabled = false;
      if (input) {
        input.focus();
        input.style.height = "auto";
      }
    }
  }

  function autoResizeChatInput(element) {
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, 132)}px`;
  }

  function placeChatPanel() {
    const panel = $("#sideChat");
    const sidebarMount = $("#sidebarChatMount");
    const mobileMount = $("#mobileChatMount");
    if (!panel) return;
    if (window.innerWidth <= 980 && mobileMount) {
      if (panel.parentElement !== mobileMount) {
        mobileMount.appendChild(panel);
      }
    } else if (sidebarMount && panel.parentElement !== sidebarMount) {
      sidebarMount.appendChild(panel);
    }
  }

  async function initSideChat() {
    getChatSessionId();
    state.chatStatus = await refreshChatStatus();
    try {
      const history = await api(
        `/api/chat/history?session_id=${encodeURIComponent(
          getChatSessionId()
        )}`
      );
      renderChatHistory(history.messages || []);
    } catch (error) {
      renderChatHistory([]);
      appendChatError(`加载历史对话失败：${error.message}`);
    }
    state.chatLoaded = true;
    scrollChat();
  }

  /* ==========================================================
     页面：发现
     ========================================================== */

  async function renderDiscover() {
    const activeFilter =
      REC_FILTERS.find((item) => item.id === state.recFilter) || REC_FILTERS[0];
    const [restaurantData, recommendationData, profileData] =
      await Promise.all([
        api("/api/restaurants"),
        api(`/api/recommendations?limit=8${activeFilter.params}`),
        api("/api/profile"),
      ]);
    state.restaurants = restaurantData.restaurants;
    state.categories = restaurantData.categories;
    state.profile = profileData;
    updateSideStats(restaurantData.stats);

    const featured = [...restaurantData.restaurants]
      .sort((left, right) => Number(right.rating) - Number(left.rating))
      .slice(0, 8);

    view.innerHTML = `
      ${topbar(restaurantData.stats)}
      ${hero(
        profileData,
        restaurantData.stats,
        (recommendationData.recommendations || [])[0]
      )}
      ${statRow(restaurantData.stats, profileData)}
      <div class="mobile-chat-mount" id="mobileChatMount"></div>
      ${recSection(recommendationData.recommendations || [])}
      <section class="section">
        <div class="section-head">
          <div class="section-title">
            <h2>附近商家</h2>
            <span class="hint">按评分排序 · 共 ${
              restaurantData.stats.restaurants
            } 家</span>
          </div>
          <a class="btn btn-ghost btn-sm" href="/stores" data-link>全部商家 ${icon(
            "arrow-right"
          )}</a>
        </div>
        <div class="store-grid">${featured.map(storeCard).join("")}</div>
      </section>`;

    refreshChatStatus().catch(() => {});
  }

  function updateSideStats(stats) {
    if (!stats) return;
    const restaurants = $("#sideStats");
    const sub = $("#sideSub");
    if (restaurants) restaurants.textContent = `${stats.restaurants} 家商家`;
    if (sub) sub.textContent = `${stats.dishes} 道菜 · ${stats.categories} 个菜系`;
  }

  /* ==========================================================
     页面：商家
     ========================================================== */

  function storesUrl({ category = "全部", q = "", sort = "rating" } = {}) {
    const params = new URLSearchParams();
    if (category && category !== "全部") params.set("category", category);
    if (q) params.set("q", q);
    if (sort && sort !== "rating") params.set("sort", sort);
    const query = params.toString();
    return `/stores${query ? `?${query}` : ""}`;
  }

  async function renderStores(params) {
    const category = params.get("category") || "全部";
    const query = params.get("q") || "";
    const sort = params.get("sort") || "rating";
    const search = new URLSearchParams({ category, sort });
    if (query) search.set("q", query);
    const data = await api(`/api/restaurants?${search.toString()}`);
    state.restaurants = data.restaurants;
    state.categories = data.categories;
    updateSideStats(data.stats);

    const chips = [
      `<a class="chip ${
        category === "全部" ? "active" : ""
      }" href="${storesUrl({ q: query, sort })}" data-link>全部 <span class="count">${
        data.stats.restaurants
      }</span></a>`,
      ...data.categories.map(
        (item) =>
          `<a class="chip ${category === item.name ? "active" : ""}" href="${storesUrl(
            { category: item.name, q: query, sort }
          )}" data-link><i class="chip-dot" style="${dotStyle(
            item.name
          )}"></i>${esc(item.name)} <span class="count">${item.count}</span></a>`
      ),
    ].join("");

    const sortOptions = [
      ["rating", "评分优先"],
      ["distance", "距离最近"],
      ["delivery", "配送费最低"],
      ["min_order", "起送价最低"],
      ["dishes", "菜品最多"],
    ];

    const grid = data.restaurants.length
      ? `<div class="store-grid">${data.restaurants
          .map(storeCard)
          .join("")}</div>`
      : emptyBlock({
          iconName: "search",
          title: "没有找到匹配的商家",
          text: "换一个菜系，或者清空搜索关键词再试试。",
          action: `<a class="btn btn-ghost" href="/stores" data-link>查看全部商家</a>`,
        });

    view.innerHTML = `
      <div class="page-head">
        <div>
          <div class="crumbs"><a href="/" data-link>首页</a>${icon(
            "chevron-right"
          )}<span>商家</span></div>
          <h1 class="page-title">附近商家</h1>
          <p class="page-sub">共 ${data.stats.restaurants} 家 · 当前显示 ${
      data.restaurants.length
    } 家 · ${data.stats.open_now} 家营业中</p>
        </div>
        <div class="top-actions">
          <a class="avatar" href="/profile" data-link title="default 用户">食</a>
        </div>
      </div>
      <div class="chip-row">${chips}</div>
      <div class="toolbar">
        <div class="toolbar-left">
          <form class="search-inline" data-search-form>
            ${icon("search")}
            <input name="q" value="${esc(query)}" placeholder="搜索商家或菜系" aria-label="搜索商家或菜系">
          </form>
          <select class="select" id="storeSort" aria-label="排序方式">
            ${sortOptions
              .map(
                ([value, label]) =>
                  `<option value="${value}" ${
                    sort === value ? "selected" : ""
                  }>${label}</option>`
              )
              .join("")}
          </select>
        </div>
        <div class="toolbar-right">
          <span class="result-count">找到 <strong>${
            data.restaurants.length
          }</strong> 家商家</span>
        </div>
      </div>
      ${grid}`;
  }

  /* ==========================================================
     页面：菜单
     ========================================================== */

  function prefsSummary(preferences = {}) {
    const parts = [];
    if (preferences.budget_max != null) {
      parts.push(`预算 ≤ ¥${money(preferences.budget_max)}`);
    }
    if (preferences.spicy_max != null) {
      parts.push(spicyCapLabel(preferences.spicy_max));
    }
    if (Array.isArray(preferences.avoided_foods) && preferences.avoided_foods.length) {
      parts.push(`忌口 ${preferences.avoided_foods.join("、")}`);
    }
    if (
      Array.isArray(preferences.preferred_categories) &&
      preferences.preferred_categories.length
    ) {
      parts.push(`偏好 ${preferences.preferred_categories.join("、")}`);
    }
    if (preferences.min_rating != null) {
      parts.push(`评分 ≥ ${preferences.min_rating}`);
    }
    return parts;
  }

  async function renderMenu(params) {
    const ePoiId =
      params.get("ePoiId") || params.get("epoiId") || "4213";
    const [data, restaurantData] = await Promise.all([
      api(`/api/menu?ePoiId=${encodeURIComponent(ePoiId)}`),
      api("/api/restaurants").catch(() => ({ restaurants: [], categories: [], stats: null })),
    ]);
    state.menu = data;
    state.currentEpoi = ePoiId;
    state.menuCategory = "全部";
    state.menuQuery = "";
    if (restaurantData.restaurants) {
      state.restaurants = restaurantData.restaurants;
      state.categories = restaurantData.categories || [];
    }
    if (restaurantData.stats) updateSideStats(restaurantData.stats);

    const restaurant = data.restaurant;
    const sameCategory = state.restaurants
      .filter(
        (item) =>
          item.category === restaurant.category &&
          String(item.e_poi_id) !== String(ePoiId)
      )
      .sort((left, right) => Number(right.rating) - Number(left.rating));
    const others = state.restaurants
      .filter(
        (item) =>
          item.category !== restaurant.category &&
          String(item.e_poi_id) !== String(ePoiId)
      )
      .sort((left, right) => Number(right.rating) - Number(left.rating));
    const similar = [...sameCategory, ...others].slice(0, 4);
    const prefs = data.preferences || {};
    const summary = prefsSummary(prefs);
    const categories = [
      { name: "全部", count: data.dishes.length },
      ...data.categories,
    ];
    const tabs = categories
      .map(
        (item) =>
          `<button class="chip ${
            item.name === "全部" ? "active" : ""
          }" data-action="menu-cat" data-category="${esc(item.name)}">${esc(
            item.name
          )} <span class="count">${item.count}</span></button>`
      )
      .join("");

    view.innerHTML = `
      <div class="crumbs"><a href="/" data-link>首页</a>${icon(
        "chevron-right"
      )}<a href="/stores" data-link>商家</a>${icon(
        "chevron-right"
      )}<span>${esc(restaurant.name)}</span></div>
      <section class="menu-hero">
        <div class="menu-seal">${esc(charOf(restaurant.category))}</div>
        <div class="menu-info">
          <h1>${esc(restaurant.name)}</h1>
          <div class="menu-tags">
            <span class="badge rating">${icon("star", "ic fill")}${ratingText(
      restaurant.rating
    )}</span>
            ${
              restaurant.is_open
                ? '<span class="badge open">营业中</span>'
                : '<span class="badge closed">休息中</span>'
            }
            <span class="badge">${esc(restaurant.category || "其他")}</span>
          </div>
          <div class="menu-meta">
            <span>${icon("pin")}距离 ${Number(
      restaurant.distance_km || 0
    ).toFixed(1)} km</span>
            <span>${icon("bike")}配送费 ¥${money(
      restaurant.delivery_fee
    )}</span>
            <span>${icon("wallet")}起送 ¥${money(
      restaurant.min_order
    )}</span>
            <span>${icon("clock")}${esc(
      restaurant.business_hours || "营业时间未知"
    )}</span>
            <span>${icon("bowl")}${restaurant.dish_count} 道菜</span>
          </div>
        </div>
        <div class="menu-actions">
          <a class="btn btn-ghost" href="/stores" data-link>${icon(
            "arrow-left"
          )}全部商家</a>
          <button class="btn btn-brand" data-action="cart-open">${icon(
            "cart"
          )}购物车 <span data-cart-count>${cartCount()}</span></button>
        </div>
      </section>
      ${
        summary.length
          ? `<div class="pref-banner">${icon(
              "sparkles"
            )}<span>你的口味：<strong>${summary.join("</strong> · <strong>")}</strong></span><span class="spacer"></span><a href="/profile" data-link>调整画像 →</a></div>`
          : `<div class="pref-banner">${icon(
              "info"
            )}<span>还没有明确偏好，先设置预算和辣度，推荐会更准。</span><span class="spacer"></span><a href="/profile" data-link>去设置 →</a></div>`
      }
      <div class="menu-toolbar">
        <div class="chip-row">${tabs}</div>
        <form class="search-inline" onsubmit="return false">
          ${icon("search")}
          <input id="menuSearch" placeholder="在本店搜索菜品" aria-label="在本店搜索菜品" autocomplete="off">
        </form>
      </div>
      <div class="toolbar" style="margin:6px 0 0">
        <div class="toolbar-left"><span class="result-count" id="menuCount"></span></div>
        <div class="toolbar-right"><span class="result-count">${icon(
          "info"
        )} 点击卡片查看详情，操作会自动写入画像</span></div>
      </div>
      <div class="dish-grid" id="dishList"></div>
      ${
        similar.length
          ? `<section class="section">
              <div class="section-head">
                <div class="section-title">
                  <h2>你可能也喜欢</h2>
                  <span class="hint">${esc(
                    restaurant.category || ""
                  )} · 同类菜系优先</span>
                </div>
                <a class="btn btn-ghost btn-sm" href="${storesUrl({
                  category: restaurant.category,
                })}" data-link>查看同类 ${icon("arrow-right")}</a>
              </div>
              <div class="store-grid">${similar.map(storeCard).join("")}</div>
            </section>`
          : ""
      }`;
    renderMenuDishes();
    updateCartBadges();
  }

  function renderMenuDishes() {
    const container = $("#dishList");
    const countLabel = $("#menuCount");
    if (!container || !state.menu) return;
    const query = state.menuQuery.trim().toLowerCase();
    const dishes = state.menu.dishes.filter((dish) => {
      const matchesCategory =
        state.menuCategory === "全部" ||
        dish.category_name === state.menuCategory;
      const haystack = `${dish.name} ${dish.tags || ""} ${
        dish.description || ""
      }`.toLowerCase();
      return matchesCategory && (!query || haystack.includes(query));
    });
    container.innerHTML = dishes.length
      ? dishes.map((dish) => dishCard(dish, { source: "menu" })).join("")
      : emptyBlock({
          iconName: "search",
          title: "这道菜还没上架",
          text: "换个关键词或分类试试，或者看看本店的其他招牌。",
        });
    if (countLabel) {
      countLabel.innerHTML = `共 <strong>${dishes.length}</strong> 道菜 · 当前分类 ${
        state.menuCategory
      }`;
    }
  }

  /* ==========================================================
     页面：画像
     ========================================================== */

  function prefDisplay(key, value) {
    if (value === undefined || value === null || value === "") {
      return `<span class="empty-value">未设置</span>`;
    }
    if (Array.isArray(value)) {
      if (!value.length) return `<span class="empty-value">未设置</span>`;
      return value.map((item) => `<span class="tag">${esc(item)}</span>`).join("");
    }
    if (key === "budget_max" || key === "delivery_fee_max") {
      return `¥${money(value)}`;
    }
    if (key === "spicy_max") {
      return esc(spicyCapLabel(value));
    }
    if (key === "min_rating") {
      return `${esc(value)} 分`;
    }
    return esc(value);
  }

  function featureWeight(feature) {
    const payload = feature?.value;
    if (payload && typeof payload === "object") {
      if (payload.normalized_weight != null) {
        return Number(payload.normalized_weight);
      }
      if (payload.raw_weight != null) return Number(payload.raw_weight);
    }
    return Number(feature?.score || 0);
  }

  function featureDirection(feature) {
    const payload = feature?.value;
    if (payload && typeof payload === "object" && payload.direction) {
      return payload.direction;
    }
    return "positive";
  }

  function metricValue(feature) {
    const payload = feature?.value;
    if (payload && typeof payload === "object" && payload.value != null) {
      return Number(payload.value);
    }
    if (typeof payload === "number") return payload;
    return null;
  }

  function metricConfidence(feature) {
    const payload = feature?.value;
    if (payload && typeof payload === "object" && payload.confidence != null) {
      return Number(payload.confidence);
    }
    return Number(feature?.confidence || 0);
  }

  function metricDisplay(kind, value) {
    if (value === null || Number.isNaN(value)) {
      return "暂无";
    }
    if (kind === "spicy") {
      return `${value.toFixed(1)}<small> / 5</small>`;
    }
    if (kind === "price") {
      return `¥${Math.round(value)}`;
    }
    if (kind === "fee") {
      return `¥${value.toFixed(1)}`;
    }
    return `${value.toFixed(1)}<small> km</small>`;
  }

  function metricGrid(metrics = {}) {
    return `<div class="metric-grid">${METRIC_META.map((meta) => {
      const feature = metrics[meta.key];
      const value = metricValue(feature);
      const confidence = Math.max(
        0,
        Math.min(1, metricConfidence(feature))
      );
      return `<div class="metric-card">
        <div class="metric-top">
          <span class="metric-icon">${icon(meta.icon)}</span>
          <span>${meta.label}</span>
        </div>
        <div class="metric-value">${metricDisplay(meta.kind, value)}</div>
        <div class="metric-label">${
          feature ? "由行为自动学习" : "暂无足够行为"
        }</div>
        <div class="conf-track"><div class="conf-fill" style="width:${Math.round(
          confidence * 100
        )}%"></div></div>
      </div>`;
    }).join("")}</div>`;
  }

  function categoryBars(categories = []) {
    if (!categories.length) {
      return `<div class="bar-empty">还没有足够的点击和下单行为，去商家页面逛逛吧。</div>`;
    }
    const top = categories.slice(0, 8);
    return `<div class="bar-list">${top
      .map(([label, feature]) => {
        const weight = featureWeight(feature);
        const width = Math.max(3, Math.round(Math.abs(weight) * 100));
        const negative = featureDirection(feature) === "negative";
        const count = feature?.value?.event_count ?? feature?.update_count ?? 0;
        return `<div class="bar-row">
          <div class="bar-label">${esc(label)}<span class="count">${count} 次</span></div>
          <div class="bar-track"><div class="bar-fill ${
            negative ? "negative" : ""
          }" style="width:${width}%"></div></div>
          <div class="bar-value">${Math.round(Math.abs(weight) * 100)}%</div>
        </div>`;
      })
      .join("")}</div>`;
  }

  function prefRows(preferences = {}) {
    return `<div class="pref-list">${PREF_ROWS.map(
      (row) => `<div class="pref-row">
        <div class="pref-key">${row.label}</div>
        <div class="pref-value">${prefDisplay(
          row.key,
          preferences[row.key]
        )}</div>
      </div>`
    ).join("")}</div>`;
  }

  function eventTimeline(events = []) {
    if (!events.length) {
      return `<div class="bar-empty">还没有行为记录，点击、收藏、下单都会进入这里。</div>`;
    }
    return `<div class="timeline">${events
      .slice(0, 12)
      .map((event) => {
        const meta = EVENT_META[event.event_type] || {
          label: event.event_type,
          icon: "info",
          weight: "",
          tone: "",
        };
        const isRating = ["rating", "rating_positive", "rating_negative"].includes(
          event.event_type
        );
        const ratingValue = event.context?.rating;
        const thing =
          event.event_type === "search"
            ? `搜索「${esc(event.search_query || "")}」`
            : `${isRating ? "评分" : meta.label}「${esc(
                event.dish_name || event.restaurant_name || "商家"
              )}」`;
        const extra =
          isRating && ratingValue != null ? ` · ${ratingValue} 分` : "";
        const ratingWeight =
          isRating && ratingValue != null ? (ratingValue - 3) * 4 : null;
        const weightText =
          ratingWeight != null
            ? `${ratingWeight >= 0 ? "+" : ""}${ratingWeight}`
            : meta.weight;
        const tone =
          ratingWeight != null
            ? ratingWeight > 0
              ? "pos"
              : ratingWeight < 0
              ? "neg"
              : ""
            : meta.tone;
        const restaurant =
          event.restaurant_name && event.dish_name
            ? `<span>${esc(event.restaurant_name)}</span>`
            : "";
        return `<div class="tl-item">
          <div class="tl-icon ${tone}">${icon(meta.icon)}</div>
          <div class="tl-body">
            <div class="tl-title">${thing}${extra}</div>
            <div class="tl-meta">
              <span>${relativeTime(event.created_at)}</span>
              ${restaurant}
              ${
                weightText
                  ? `<span class="tl-weight ${tone}">${weightText}</span>`
                  : ""
              }
            </div>
          </div>
        </div>`;
      })
      .join("")}</div>`;
  }

  function orderList(orders = []) {
    if (!orders.length) {
      return `<div class="bar-empty">还没有订单，去菜单里下一单试试。</div>`;
    }
    return `<div class="order-list">${orders
      .slice(0, 6)
      .map(
        (order) => `<div class="order-item">
          <div class="order-main">
            <h4>${esc(order.dish_name || "外卖订单")}</h4>
            <p>${esc(order.restaurant_name || "")} · ${dateText(
          order.created_at
        )}</p>
          </div>
          <div class="order-side">
            <strong>¥${money(order.price)}</strong>
            <span>${order.rating ? `${order.rating} 分` : "已完成"}</span>
          </div>
        </div>`
      )
      .join("")}</div>`;
  }

  function featureChips(items, emptyText) {
    const positive = items.filter(
      ([, feature]) =>
        featureWeight(feature) > 0 && featureDirection(feature) !== "negative"
    );
    if (!positive.length) {
      return `<div class="bar-empty" style="padding:12px 0">${esc(
        emptyText
      )}</div>`;
    }
    return `<div class="feature-chips">${positive
      .slice(0, 6)
      .map(
        ([label, feature]) =>
          `<span class="tag feature-tag">${esc(label)}<b>${Math.round(
            Math.abs(featureWeight(feature)) * 100
          )}%</b></span>`
      )
      .join("")}</div>`;
  }

  async function renderProfile() {
    const [data, restaurantData] = await Promise.all([
      api("/api/profile"),
      api("/api/restaurants"),
    ]);
    state.profile = data;
    state.categories = restaurantData.categories;
    updateSideStats(restaurantData.stats);

    const summary = data.summary || {};
    const preferences = summary.explicit_preferences || {};
    const stats = data.stats || {};
    const tags = [
      `<span class="badge accent">画像 ${summary.feature_count || 0} 维</span>`,
      ...prefsSummary(preferences)
        .slice(0, 4)
        .map((text) => `<span class="badge">${esc(text)}</span>`),
      `<span class="badge">${
        summary.user_id || "default"
      } · 本地用户</span>`,
    ].join("");

    view.innerHTML = `
      <div class="crumbs"><a href="/" data-link>首页</a>${icon(
        "chevron-right"
      )}<span>我的口味</span></div>
      <section class="profile-hero">
        <div class="profile-avatar">食</div>
        <div class="profile-id">
          <div class="eyebrow">TASTE PROFILE · 本地单用户画像</div>
          <h1>我的口味</h1>
          <div class="profile-tags">${tags}</div>
        </div>
        <div class="profile-actions">
          <button class="btn btn-brand" data-action="prefs-edit">${icon(
            "sliders"
          )}调整画像</button>
          <a class="btn btn-ghost" href="/" data-link>${icon(
            "compass"
          )}去发现</a>
        </div>
      </section>
      ${metricGrid(summary.metrics || {})}
      <div class="stat-strip">
        <div class="stat"><span class="stat-icon">${icon(
          "eye"
        )}</span><div><strong>${stats.events || 0}</strong><span>行为事件</span></div></div>
        <div class="stat"><span class="stat-icon">${icon(
          "heart"
        )}</span><div><strong>${stats.favorites || 0}</strong><span>收藏</span></div></div>
        <div class="stat"><span class="stat-icon">${icon(
          "check"
        )}</span><div><strong>${stats.orders || 0}</strong><span>订单</span></div></div>
        <div class="stat"><span class="stat-icon">${icon(
          "bowl"
        )}</span><div><strong>${
      stats.tried_dishes || 0
    }</strong><span>尝过的菜品</span></div></div>
      </div>
      <div class="split">
        <div class="stack">
          <section class="panel">
            <div class="panel-head">
              <div class="panel-title">${icon("flame")}菜系偏好</div>
              <span class="panel-sub">行为权重归一化</span>
            </div>
            <div class="panel-body">${categoryBars(
              summary.categories || []
            )}</div>
          </section>
          <section class="panel">
            <div class="panel-head">
              <div class="panel-title">${icon("tag")}高频菜品与商家</div>
              <span class="panel-sub">行为权重 Top</span>
            </div>
            <div class="panel-body">
              <div class="mini-label">菜品</div>
              ${featureChips(summary.dishes || [], "暂无菜品偏好")}
              <div class="mini-label" style="margin-top:14px">商家</div>
              ${featureChips(summary.restaurants || [], "暂无商家偏好")}
            </div>
          </section>
        </div>
        <section class="panel">
          <div class="panel-head">
            <div class="panel-title">${icon("sliders")}明确偏好</div>
            <button class="pref-edit-btn" data-action="prefs-edit">${icon(
              "edit"
            )}编辑</button>
          </div>
          <div class="panel-body">${prefRows(preferences)}</div>
        </section>
      </div>
      <div class="split">
        <section class="panel">
          <div class="panel-head">
            <div class="panel-title">${icon("eye")}最近行为</div>
            <div class="segmented">
              <button class="${
                state.eventFilter === "behavior" ? "active" : ""
              }" data-action="event-filter" data-filter="behavior">推荐行为</button>
              <button class="${
                state.eventFilter === "all" ? "active" : ""
              }" data-action="event-filter" data-filter="all">全部</button>
            </div>
          </div>
          <div class="panel-body">
            <div class="event-summary">共 ${
              stats.events || 0
            } 条行为记录 · 展示最近 12 条</div>
            <div id="eventTimeline">${eventTimeline(
              state.eventFilter === "behavior"
                ? (data.events || []).filter(
                    (event) => event.event_type !== "search"
                  )
                : data.events || []
            )}</div>
          </div>
        </section>
        <section class="panel">
          <div class="panel-head">
            <div class="panel-title">${icon("wallet")}最近订单</div>
            <span class="panel-sub">最近 ${Math.min(
              (data.orders || []).length,
              6
            )} 单</span>
          </div>
          <div class="panel-body">${orderList(data.orders || [])}</div>
        </section>
      </div>`;
  }

  /* ==========================================================
     画像编辑
     ========================================================== */

  function openPrefsModal() {
    const preferences =
      state.profile?.summary?.explicit_preferences || {};
    const categories = (state.categories || []).map((item) => item.name);
    const selected = new Set(
      Array.isArray(preferences.preferred_categories)
        ? preferences.preferred_categories
        : []
    );
    const ratingValue =
      preferences.min_rating != null ? String(preferences.min_rating) : "";
    const ratingOptions = ["", "4.0", "4.3", "4.5", "4.7"];
    if (ratingValue && !ratingOptions.includes(ratingValue)) {
      ratingOptions.push(ratingValue);
    }

    openModal(`<div class="modal-backdrop" data-close-modal>
      <div class="modal" role="dialog" aria-modal="true" aria-label="调整口味画像">
        <div class="modal-head">
          <div>
            <h2>调整口味画像</h2>
            <div class="sub">明确偏好的优先级最高，保存后立即影响推荐</div>
          </div>
          <button class="icon-btn" data-action="modal-close" aria-label="关闭">${icon(
            "close"
          )}</button>
        </div>
        <div class="modal-body">
          <div class="form-grid">
            <div class="field">
              <label for="prefBudget">预算上限 <span class="opt">元</span></label>
              <input id="prefBudget" type="number" min="1" step="1" placeholder="不限" value="${
                preferences.budget_max != null
                  ? esc(preferences.budget_max)
                  : ""
              }">
            </div>
            <div class="field">
              <label for="prefFee">配送费上限 <span class="opt">元</span></label>
              <input id="prefFee" type="number" min="0" step="1" placeholder="不限" value="${
                preferences.delivery_fee_max != null
                  ? esc(preferences.delivery_fee_max)
                  : ""
              }">
            </div>
            <div class="field">
              <label for="prefRating">最低评分</label>
              <select id="prefRating">
                ${ratingOptions
                  .map(
                    (value) =>
                      `<option value="${value}" ${
                        value === ratingValue ? "selected" : ""
                      }>${value ? `${value} 分以上` : "不限"}</option>`
                  )
                  .join("")}
              </select>
            </div>
            <div class="field">
              <label for="prefSpicy">辣度上限</label>
              <div class="range-row">
                <input id="prefSpicy" type="range" min="0" max="5" step="1" value="${
                  preferences.spicy_max != null
                    ? Number(preferences.spicy_max)
                    : 5
                }">
                <span class="range-value" id="spicyValue">${spicyCapLabel(
                  preferences.spicy_max != null
                    ? preferences.spicy_max
                    : 5
                )}</span>
              </div>
            </div>
            <div class="field full">
              <label>偏好菜系</label>
              <div class="choice-row" id="prefCats">
                ${categories
                  .map(
                    (name) =>
                      `<button class="choice ${
                        selected.has(name) ? "on" : ""
                      }" data-action="pref-choice" data-value="${esc(
                        name
                      )}">${esc(name)}</button>`
                  )
                  .join("")}
              </div>
              <div class="field-help">可多选，推荐会优先匹配这些菜系</div>
            </div>
            <div class="field full">
              <label for="prefAvoid">忌口菜品</label>
              <input id="prefAvoid" type="text" placeholder="用逗号分隔，例如：猪脚饭，香菜" value="${esc(
                Array.isArray(preferences.avoided_foods)
                  ? preferences.avoided_foods.join("，")
                  : ""
              )}">
              <div class="field-help">推荐时会直接过滤掉包含这些词的菜</div>
            </div>
            <div class="field full">
              <label for="prefNotes">备注 <span class="opt">可选</span></label>
              <textarea id="prefNotes" placeholder="例如：工作日午餐尽量控制在 30 元以内">${esc(
                preferences.notes || ""
              )}</textarea>
            </div>
          </div>
        </div>
        <div class="modal-foot">
          <span class="spacer"></span>
          <button class="btn btn-ghost" data-action="modal-close">取消</button>
          <button class="btn btn-primary" data-action="prefs-save">${icon(
            "check"
          )}保存画像</button>
        </div>
      </div>
    </div>`);
  }

  async function savePreferences() {
    const current =
      state.profile?.summary?.explicit_preferences || {};
    const operations = [];
    const setValue = (key, value) => operations.push({ key, value });
    const deleteValue = (key) => {
      if (Object.prototype.hasOwnProperty.call(current, key)) {
        operations.push({ key, delete: true });
      }
    };

    const budget = numberOrNull($("#prefBudget")?.value);
    if (budget !== null) setValue("budget_max", budget);
    else deleteValue("budget_max");

    const fee = numberOrNull($("#prefFee")?.value);
    if (fee !== null) setValue("delivery_fee_max", fee);
    else deleteValue("delivery_fee_max");

    const rating = ($("#prefRating")?.value || "").trim();
    if (rating) setValue("min_rating", Number(rating));
    else deleteValue("min_rating");

    const spicy = numberOrNull($("#prefSpicy")?.value);
    if (spicy !== null && spicy < 5) setValue("spicy_max", spicy);
    else deleteValue("spicy_max");

    const cats = $$("#prefCats .choice.on").map((element) => element.dataset.value);
    if (cats.length) setValue("preferred_categories", cats);
    else deleteValue("preferred_categories");

    const avoid = String($("#prefAvoid")?.value || "")
      .split(/[,，]/)
      .map((item) => item.trim())
      .filter(Boolean);
    if (avoid.length) setValue("avoided_foods", avoid);
    else deleteValue("avoided_foods");

    const notes = String($("#prefNotes")?.value || "").trim();
    if (notes) setValue("notes", notes);
    else deleteValue("notes");

    const button = $('[data-action="prefs-save"]');
    if (button) {
      button.disabled = true;
      button.textContent = "保存中…";
    }
    try {
      for (const operation of operations) {
        await api("/api/preferences", {
          method: "POST",
          body: JSON.stringify(operation),
        });
      }
      toast("口味画像已更新，推荐已重新排序");
      closeModal();
      await router();
    } catch (error) {
      toast(error.message, "error");
      if (button) {
        button.disabled = false;
        button.textContent = "保存画像";
      }
    }
  }

  /* ==========================================================
     页面：搜索
     ========================================================== */

  async function renderSearch(params) {
    const query = (params.get("q") || "").trim();
    const escapeHint = ["川菜", "面食", "轻食", "日料", "火锅", "烧烤"]
      .map(
        (term) =>
          `<button class="hero-chip" data-action="search-term" data-q="${term}">${term}</button>`
      )
      .join("");

    const shell = `<section class="search-hero">
      <div class="search-art" aria-hidden="true"><span>${esc(
        query ? charOf(query) : "食"
      )}</span></div>
      <div class="eyebrow">SEARCH · 饭点搜索</div>
      <h1>今天想吃什么？<em>搜一下</em></h1>
      <form class="search-big" data-search-form>
        ${icon("search")}
        <input name="q" value="${esc(query)}" placeholder="菜品、菜系或商家名，例如「牛肉面」" autocomplete="off" autofocus aria-label="搜索">
        <button class="btn btn-brand" type="submit">搜索</button>
      </form>
      ${
        query
          ? ""
          : `<div class="hero-chips" style="margin-top:16px"><span class="label">热门</span>${escapeHint}</div>`
      }
    </section>
    <div id="searchResults"></div>`;

    view.innerHTML = shell;
    if (!query) {
      $("#searchResults").innerHTML = `<div style="margin-top:28px">${emptyBlock(
        {
          iconName: "search",
          title: "搜点什么吧",
          text: "试试菜名、菜系或者商家名，比如「麻婆豆腐」「川菜」「轻食」。",
        }
      )}</div>`;
      return;
    }

    recordSearchOnce(query);
    const data = await api(`/api/search?q=${encodeURIComponent(query)}`);
    const stores = data.restaurants || [];
    const dishes = data.dishes || [];
    const results = [];

    if (stores.length) {
      results.push(`<section class="result-section">
        <div class="section-head">
          <div class="section-title"><h2>相关商家</h2><span class="hint">${
            stores.length
          } 家</span></div>
        </div>
        <div class="store-grid">${stores
          .map((store, index) => storeCard(store, index))
          .join("")}</div>
      </section>`);
    }
    if (dishes.length) {
      results.push(`<section class="result-section">
        <div class="section-head">
          <div class="section-title"><h2>相关菜品</h2><span class="hint">${
            dishes.length
          } 道 · 按月售排序</span></div>
        </div>
        <div class="dish-grid">${dishes
          .map((dish) => dishCard(dish, { showStore: true, source: "search" }))
          .join("")}</div>
      </section>`);
    }
    if (!results.length) {
      results.push(`<div style="margin-top:28px">${emptyBlock({
        iconName: "search",
        title: `没有找到「${query}」`,
        text: "试试更短的关键词，或者从热门菜系里挑一个。",
        action: `<a class="btn btn-ghost" href="/stores" data-link>看看全部商家</a>`,
      })}</div>`);
    }

    $("#searchResults").innerHTML = results.join("");
  }

  /* ==========================================================
     路由
     ========================================================== */

  const ROUTES = [
    { pattern: /^\/$/, name: "discover", render: renderDiscover },
    { pattern: /^\/stores$/, name: "stores", render: renderStores },
    { pattern: /^\/menu$/, name: "menu", render: renderMenu },
    { pattern: /^\/profile$/, name: "profile", render: renderProfile },
    { pattern: /^\/search$/, name: "search", render: renderSearch },
  ];

  function setActiveNav(name) {
    $$("[data-nav]").forEach((element) => {
      element.classList.toggle("active", element.dataset.nav === name);
    });
  }

  async function router() {
    const path = location.pathname.replace(/\/+$/, "") || "/";
    const route =
      ROUTES.find((item) => item.pattern.test(path)) || ROUTES[0];
    const panel = $("#sideChat");
    const sidebarMount = $("#sidebarChatMount");
    if (panel && sidebarMount) {
      sidebarMount.appendChild(panel);
    }
    closeModal();
    if (state.cartOpen) closeCart();
    setActiveNav(route.name === "menu" ? "discover" : route.name);
    view.innerHTML = skeletonFor(route.name);
    try {
      await route.render(new URLSearchParams(location.search));
      placeChatPanel();
      window.scrollTo({ top: 0, behavior: "auto" });
    } catch (error) {
      console.error(error);
      view.innerHTML = `<div class="error-view">
        <div class="empty-art">${icon("info")}</div>
        <h2>页面加载失败</h2>
        <p>${esc(error.message)}</p>
        <button class="btn btn-primary" data-action="retry">${icon(
          "refresh"
        )}重新加载</button>
      </div>`;
    }
  }

  function navigate(url) {
    closeModal();
    if (state.cartOpen) {
      state.cartOpen = false;
      renderCart();
    }
    if (url === location.pathname + location.search) {
      router();
      return;
    }
    history.pushState({}, "", url);
    router();
  }

  /* ==========================================================
     交互
     ========================================================== */

  async function handleAction(element, event) {
    const action = element.dataset.action;
    const key = element.dataset.key;
    const dish = key ? getDish(key) : null;

    switch (action) {
      case "retry":
        await router();
        break;
      case "modal-close":
        closeModal();
        break;
      case "cart-open":
        openCart();
        break;
      case "cart-close":
        closeCart();
        break;
      case "cart-inc":
        changeCartQty(element.dataset.key, 1);
        break;
      case "cart-dec":
        changeCartQty(element.dataset.key, -1);
        break;
      case "checkout":
        await checkout();
        break;
      case "rec-filter":
        await applyRecFilter(element.dataset.filter);
        break;
      case "rail-scroll": {
        const rail = $("#recRail");
        const direction = Number(element.dataset.dir || 1);
        if (rail) {
          rail.scrollBy({
            left: direction * Math.max(320, rail.clientWidth * 0.8),
            behavior: "smooth",
          });
        }
        break;
      }
      case "search-term":
        navigate(`/search?q=${encodeURIComponent(element.dataset.q)}`);
        break;
      case "lucky":
        await luckyPick();
        break;
      case "menu-cat":
        state.menuCategory = element.dataset.category || "全部";
        $$('[data-action="menu-cat"]').forEach((chip) => {
          chip.classList.toggle(
            "active",
            chip.dataset.category === state.menuCategory
          );
        });
        renderMenuDishes();
        break;
      case "add-cart":
        addToCart(dish);
        break;
      case "favorite": {
        if (!dish) break;
        const result = await recordAction("favorite", dish);
        if (result) {
          element.classList.add("active");
          toast(`已收藏「${dish.name}」 · 画像 +4`);
        }
        break;
      }
      case "detail":
        if (dish) {
          recordAction("detail_view", dish, { silent: true });
          openDishModal(dish);
        }
        break;
      case "not-interested": {
        if (!dish) break;
        const result = await recordAction("not_interested", dish);
        if (result) {
          toast(`已对「${dish.name}」不感兴趣 · 画像 -10`);
          closeModal();
        }
        break;
      }
      case "order": {
        if (!dish) break;
        const result = await recordAction("order", dish);
        if (result) toast(`已下单「${dish.name}」 · 画像 +15`);
        break;
      }
      case "rate": {
        if (!dish) break;
        const value = Number(element.dataset.value);
        const result = await recordAction("rating", dish, { rating: value });
        if (result) {
          $$(".star-btn", modalRoot).forEach((star) => {
            star.classList.toggle(
              "on",
              Number(star.dataset.value) <= value
            );
          });
          toast(
            `已评分 ${value} 分 · 画像 ${
              value >= 3 ? `+${(value - 3) * 4}` : (value - 3) * 4
            }`
          );
        }
        break;
      }
      case "prefs-edit":
        openPrefsModal();
        break;
      case "chat-new":
        if (state.chatBusy) {
          toast("正在回答上一个问题，请稍等");
          break;
        }
        newChatSession();
        state.chatLoaded = true;
        removeChatTyping();
        renderChatHistory([]);
        $("#chatInput")?.focus();
        break;
      case "chat-suggest":
        await sendChatMessage(element.dataset.q);
        break;
      case "chat-check": {
        const status = await refreshChatStatus();
        if (status.ready) {
          const alert = $(".chat-alert");
          if (alert) alert.remove();
          toast("AI 后端已就绪");
        } else {
          toast("仍未就绪，请双击 查看AI状态.bat 检查", "error");
        }
        break;
      }
      case "event-filter": {
        state.eventFilter = element.dataset.filter || "behavior";
        $$('[data-action="event-filter"]').forEach((button) => {
          button.classList.toggle(
            "active",
            button.dataset.filter === state.eventFilter
          );
        });
        const events = state.profile?.events || [];
        const filtered =
          state.eventFilter === "behavior"
            ? events.filter((event) => event.event_type !== "search")
            : events;
        const container = $("#eventTimeline");
        if (container) container.innerHTML = eventTimeline(filtered);
        break;
      }
      case "prefs-save":
        await savePreferences();
        break;
      case "pref-choice":
        element.classList.toggle("on");
        break;
      default:
        break;
    }
  }

  document.addEventListener("click", (event) => {
    const link = event.target.closest("a[data-link]");
    if (link) {
      event.preventDefault();
      navigate(link.getAttribute("href"));
      return;
    }

    const backdrop = event.target.closest("[data-close-modal]");
    if (backdrop && event.target === backdrop) {
      closeModal();
      return;
    }

    const actionElement = event.target.closest("[data-action]");
    if (actionElement) {
      event.preventDefault();
      handleAction(actionElement, event).catch((error) => {
        console.error(error);
        toast(error.message || "操作失败", "error");
      });
      return;
    }

    const storeElement = event.target.closest("[data-open-store]");
    if (storeElement) {
      navigate(
        `/menu?ePoiId=${encodeURIComponent(storeElement.dataset.openStore)}`
      );
      return;
    }

    const dishElement = event.target.closest("[data-open-dish]");
    if (dishElement) {
      const dishItem = getDish(dishElement.dataset.openDish);
      if (!dishItem) return;
      if (!dishItem.soldOut) {
        recordAction("click", dishItem, { silent: true });
      }
      openDishModal(dishItem);
    }
  });

  document.addEventListener("submit", (event) => {
    const chatForm = event.target.closest("[data-chat-form]");
    if (chatForm) {
      event.preventDefault();
      sendChatMessage($("#chatInput")?.value);
      return;
    }

    const form = event.target.closest("[data-search-form]");
    if (!form) return;
    event.preventDefault();
    const input = form.querySelector('input[name="q"]');
    const query = (input?.value || "").trim();
    if (!query) {
      toast("输入想吃的菜或菜系");
      input?.focus();
      return;
    }
    navigate(`/search?q=${encodeURIComponent(query)}`);
  });

  document.addEventListener("input", (event) => {
    if (event.target.id === "prefSpicy") {
      const label = $("#spicyValue");
      if (label) label.textContent = spicyCapLabel(event.target.value);
    }
    if (event.target.id === "menuSearch") {
      state.menuQuery = event.target.value;
      renderMenuDishes();
    }
    if (event.target.id === "chatInput") {
      autoResizeChatInput(event.target);
    }
  });

  document.addEventListener("change", (event) => {
    if (event.target.id === "storeSort") {
      const params = new URLSearchParams(location.search);
      params.set("sort", event.target.value);
      navigate(`/stores?${params.toString()}`);
    }
  });

  document.addEventListener("keydown", (event) => {
    if (
      event.target.id === "chatInput" &&
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.isComposing
    ) {
      event.preventDefault();
      sendChatMessage(event.target.value);
      return;
    }
    if (event.key !== "Escape") return;
    if (modalRoot.innerHTML) {
      closeModal();
      return;
    }
    if (state.cartOpen) closeCart();
  });

  window.addEventListener("popstate", () => {
    router();
  });

  window.addEventListener("resize", () => {
    placeChatPanel();
  });

  /* ==========================================================
     启动
     ========================================================== */

  placeChatPanel();
  initSideChat().catch(() => {});
  renderCart();
  router();
})();
