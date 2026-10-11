(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const distance = $("distance");
  let direction = "toward";

  function displayMillimeters(value) {
    return `${value.toFixed(1)} mm`;
  }

  function updateLab() {
    const error = Number(distance.value);
    const fixed = 5;
    const adaptive = Math.min(10, 0.7 * error);
    const toward = direction === "toward";
    const fixedAfter = toward ? Math.abs(error - fixed) : error + fixed;
    const adaptiveAfter = toward ? Math.abs(error - adaptive) : error + adaptive;

    $("distance-value").innerHTML = `${error.toFixed(1)} <small>mm</small>`;
    $("fixed-command").textContent = displayMillimeters(fixed);
    $("adaptive-command").textContent = displayMillimeters(adaptive);
    $("fixed-error").textContent = displayMillimeters(fixedAfter);
    $("adaptive-error").textContent = displayMillimeters(adaptiveAfter);
    $("fixed-bar").style.width = `${Math.min(100, (fixedAfter / 40) * 100)}%`;
    $("adaptive-bar").style.width = `${Math.min(100, (adaptiveAfter / 40) * 100)}%`;
    distance.style.setProperty("--range-progress", `${((error - 0.5) / 29.5) * 100}%`);

    if (!toward) {
      $("lab-verdict").textContent = "方向背离目标时，两种幅度都会增加误差；调幅无法替方向纠错。";
    } else if (adaptiveAfter + 0.001 < fixedAfter) {
      $("lab-verdict").textContent = "在这个理想例子里，Q 走得更接近目标。";
    } else if (fixedAfter + 0.001 < adaptiveAfter) {
      $("lab-verdict").textContent = "在这个理想例子里，固定 5 mm 的剩余误差更小。";
    } else {
      $("lab-verdict").textContent = "在这个理想例子里，两种步长的剩余误差相同。";
    }
  }

  distance.addEventListener("input", updateLab);
  document.querySelectorAll("[data-direction]").forEach((button) => {
    button.addEventListener("click", () => {
      direction = button.dataset.direction;
      document.querySelectorAll("[data-direction]").forEach((candidate) => {
        const active = candidate === button;
        candidate.classList.toggle("is-active", active);
        candidate.setAttribute("aria-pressed", String(active));
      });
      updateLab();
    });
  });

  // Frozen results from LOGS/2026-10-08-settled-q-transfer-results.md.
  // The task switch changes presentation only; it never estimates new outcomes.
  const tasks = {
    bowl: {
      label: "LIBERO_SPATIAL : 988",
      title: "把黑碗放到盘上",
      description: "官方初态 14–18，本轮未用来调整 Q。每条轨迹从重放后的停稳近目标状态开始。",
      threshold: "≤ 4 mm",
      note: "黑碗的 1 例之差很小：固定 5 mm 的 init15 距门槛仅 0.152 mm。",
      total: 5,
      scores: [
        { name: "Jev + Q", reached: 3, actions: 18, kind: "adaptive" },
        { name: "Jev + 5 mm", reached: 2, actions: 19, kind: "fixed" },
        { name: "直接 + Q", reached: 3, actions: 18, kind: "direct" },
      ],
      cases: [
        ["14", "14.763", "未达 · 4次 · 5.298", "未达 · 4次 · 9.087", "未达 · 4次 · 5.298"],
        ["15", "12.290", "到达 · 4次 · 3.283", "未达 · 4次 · 4.152", "到达 · 4次 · 3.283"],
        ["16", "12.022", "到达 · 3次 · 2.985", "到达 · 3次 · 3.547", "到达 · 3次 · 2.985"],
        ["17", "11.778", "到达 · 3次 · 3.585", "到达 · 4次 · 3.024", "到达 · 3次 · 3.585"],
        ["18", "14.805", "未达 · 4次 · 4.887", "未达 · 4次 · 9.185", "未达 · 4次 · 4.887"],
      ],
    },
    cheese: {
      label: "LIBERO_OBJECT : 1066",
      title: "把奶酪放进篮子",
      description: "官方初态 7–9 已在前一轮单步实验里见过，只能作为跨任务的开发诊断。",
      threshold: "≤ 2 mm",
      note: "三组都到达；共用 Q 用 11 次动作，比 Jev 固定 5 mm 的 9 次更多。",
      total: 3,
      scores: [
        { name: "Jev + Q", reached: 3, actions: 11, kind: "adaptive" },
        { name: "Jev + 5 mm", reached: 3, actions: 9, kind: "fixed" },
        { name: "直接 + Q", reached: 3, actions: 11, kind: "direct" },
      ],
      cases: [
        ["7", "6.442", "到达 · 3次 · 1.676", "到达 · 2次 · 1.759", "到达 · 3次 · 1.676"],
        ["8", "8.125", "到达 · 4次 · 1.790", "到达 · 4次 · 1.413", "到达 · 4次 · 1.790"],
        ["9", "6.258", "到达 · 4次 · 1.620", "到达 · 3次 · 1.477", "到达 · 4次 · 1.620"],
      ],
    },
  };

  function node(tag, className, content) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (content !== undefined) element.textContent = content;
    return element;
  }

  function showTask(taskKey) {
    const task = tasks[taskKey];
    $("task-label").textContent = task.label;
    $("task-title").textContent = task.title;
    $("task-description").textContent = task.description;
    $("task-threshold").textContent = task.threshold;
    $("task-note").textContent = task.note;

    document.querySelectorAll("[data-task]").forEach((button) => {
      const active = button.dataset.task === taskKey;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });

    const scores = $("score-rows");
    scores.replaceChildren();
    task.scores.forEach((score) => {
      const row = node("div", `score-row ${score.kind}`);
      const barOuter = node("div", "score-bar-outer");
      const bar = node("div", "score-bar", `${score.reached}/${task.total}`);
      bar.style.width = `${(score.reached / task.total) * 100}%`;
      barOuter.append(bar);
      row.append(node("span", "score-name", score.name), barOuter, node("span", "score-count", `${score.actions} 次`));
      scores.append(row);
    });

    const cases = $("case-rows");
    cases.replaceChildren();
    task.cases.forEach((record) => {
      const row = node("tr");
      record.forEach((value, index) => {
        const cell = node("td", value.startsWith("未达") ? "miss" : "", index === 1 ? `${value} mm` : value);
        row.append(cell);
      });
      cases.append(row);
    });
  }

  document.querySelectorAll("[data-task]").forEach((button) => {
    button.addEventListener("click", () => showTask(button.dataset.task));
  });

  if ("IntersectionObserver" in window) {
    const links = [...document.querySelectorAll(".section-nav a")];
    const observer = new IntersectionObserver((entries) => {
      const visible = entries.filter((entry) => entry.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (!visible) return;
      links.forEach((link) => link.classList.toggle("is-active", link.hash === `#${visible.target.id}`));
    }, { rootMargin: "-24% 0px -60% 0px", threshold: [0, 0.1, 0.3] });
    ["frame", "lab", "story", "comparison", "finding"].forEach((id) => observer.observe($(id)));
  }

  updateLab();
  showTask("bowl");
})();
