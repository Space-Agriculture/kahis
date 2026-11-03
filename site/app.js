(() => {
  const PALETTE = [
    "#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#46f0f0", "#f032e6",
    "#bcf60c", "#fabebe", "#008080", "#e6beff", "#9a6324", "#fffac8", "#800000",
    "#aaffc3", "#808000", "#ffd8b1", "#000075", "#808080", "#ffe119",
  ];
  const TABLE_LIMIT = 1000;

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (n) => n.toLocaleString("ko-KR");
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

  const map = L.map("map", { preferCanvas: true }).setView([36.3, 127.8], 7);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);
  const cluster = L.markerClusterGroup({ chunkedLoading: true, maxClusterRadius: 40, spiderfyDistanceMultiplier: 1.5 });
  map.addLayer(cluster);

  let data, records;
  const state = { from: "", to: "", species: new Set(), diseases: new Set() };

  function colorOf(d) {
    return PALETTE[d % PALETTE.length];
  }

  function setRange(range) {
    const to = new Date();
    const from = new Date(to);
    if (range === "7d") from.setDate(from.getDate() - 7);
    else if (range === "1m") from.setMonth(from.getMonth() - 1);
    else if (range === "3m") from.setMonth(from.getMonth() - 3);
    else if (range === "1y") from.setFullYear(from.getFullYear() - 1);
    state.from = range === "all" ? records.reduce((m, r) => (r.diag && r.diag < m ? r.diag : m), "9999-12-31") : iso(from);
    state.to = iso(to);
    $("from").value = state.from;
    $("to").value = state.to;
    document.querySelectorAll(".quick button").forEach((b) => b.classList.toggle("active", b.dataset.range === range));
  }

  function buildChecks(containerId, labels, set, withColor) {
    const box = $(containerId);
    box.innerHTML = "";
    labels.forEach((name, i) => {
      set.add(i);
      const label = document.createElement("label");
      label.dataset.idx = i;
      label.innerHTML =
        `<input type="checkbox" checked value="${i}" />` +
        (withColor ? `<span class="swatch" style="background:${colorOf(i)}"></span>` : "") +
        `<span>${esc(name || "(미상)")}</span><span class="count"></span>`;
      label.querySelector("input").addEventListener("change", (e) => {
        e.target.checked ? set.add(i) : set.delete(i);
        render();
      });
      box.appendChild(label);
    });
  }

  function updateCounts(containerId, counts) {
    const box = $(containerId);
    const labels = [...box.children];
    labels.forEach((l) => {
      const c = counts[l.dataset.idx] || 0;
      l.querySelector(".count").textContent = fmt(c);
      l.classList.toggle("zero", c === 0);
    });
    labels.sort((a, b) => (counts[b.dataset.idx] || 0) - (counts[a.dataset.idx] || 0) || a.dataset.idx - b.dataset.idx);
    labels.forEach((l) => box.appendChild(l));
  }

  function popupHtml(r) {
    const sp = data.species[r.species] + (r.breed ? `(${r.breed})` : "");
    return `<div class="popup">
      <h3><span class="swatch" style="display:inline-block;background:${colorOf(r.disease)}"></span> ${esc(data.diseases[r.disease])}</h3>
      <div>${esc(r.addr)}${r.precision === 1 ? ' <span class="muted">(상위 행정구역 위치)</span>' : ""}</div>
      <div>농장: ${esc(r.farm || "-")} · ${esc(sp)} · ${r.heads ?? "-"}두</div>
      <div>발생 ${esc(r.occur)} / 진단 ${esc(r.diag)}${r.end ? ` / 종식 ${esc(r.end)}` : ""}</div>
      <div class="muted">${esc(r.lab)}</div>
    </div>`;
  }

  function render() {
    const { from, to, species, diseases } = state;
    const inRange = records.filter((r) => r.diag >= from && r.diag <= to);

    const dCounts = {}, sCounts = {};
    for (const r of inRange) {
      if (species.has(r.species)) dCounts[r.disease] = (dCounts[r.disease] || 0) + 1;
      if (diseases.has(r.disease)) sCounts[r.species] = (sCounts[r.species] || 0) + 1;
    }
    updateCounts("diseases", dCounts);
    updateCounts("species", sCounts);

    const rows = inRange.filter((r) => species.has(r.species) && diseases.has(r.disease));

    cluster.clearLayers();
    const markers = [];
    let noLoc = 0, heads = 0;
    for (const r of rows) {
      heads += r.heads || 0;
      if (r.lat == null) { noLoc++; continue; }
      const m = L.circleMarker([r.lat, r.lng], {
        radius: 7, color: "#333", weight: 1, fillColor: colorOf(r.disease), fillOpacity: 0.85,
      });
      m.bindPopup(() => popupHtml(r));
      markers.push(m);
    }
    cluster.addLayers(markers);

    const farms = new Set(rows.map((r) => r.addr + "|" + r.farm)).size;
    $("summary").innerHTML = `
      <h2>요약</h2>
      <div class="stat"><span>발생 건수</span><b>${fmt(rows.length)}</b></div>
      <div class="stat"><span>발생 두수</span><b>${fmt(heads)}</b></div>
      <div class="stat"><span>농장 수</span><b>${fmt(farms)}</b></div>
      ${noLoc ? `<div class="muted">위치를 찾지 못한 ${fmt(noLoc)}건은 지도에 표시되지 않습니다.</div>` : ""}`;

    $("rows").innerHTML = rows.slice(0, TABLE_LIMIT).map((r) => `<tr>
      <td>${esc(r.diag)}</td><td>${esc(r.occur)}</td>
      <td><span class="swatch" style="display:inline-block;background:${colorOf(r.disease)}"></span> ${esc(data.diseases[r.disease])}</td>
      <td>${esc(data.species[r.species])}${r.breed ? `(${esc(r.breed)})` : ""}</td>
      <td>${esc(r.farm)}</td><td>${esc(r.addr)}</td><td>${r.heads ?? "-"}</td>
      <td>${esc(r.lab)}</td><td>${esc(r.end)}</td></tr>`).join("");
    $("table-note").textContent = rows.length > TABLE_LIMIT
      ? `최근 ${fmt(TABLE_LIMIT)}건만 표에 표시합니다. 전체 데이터는 CSV를 내려받아 확인하세요.`
      : rows.length === 0 ? "조건에 맞는 발생 기록이 없습니다." : "";
  }

  function bind() {
    document.querySelectorAll(".quick button").forEach((b) =>
      b.addEventListener("click", () => { setRange(b.dataset.range); render(); }));
    ["from", "to"].forEach((id) => $(id).addEventListener("change", () => {
      state[id] = $(id).value;
      document.querySelectorAll(".quick button").forEach((b) => b.classList.remove("active"));
      render();
    }));
    document.querySelectorAll(".toggle a").forEach((a) => a.addEventListener("click", (e) => {
      e.preventDefault();
      const set = state[a.dataset.target];
      const on = a.dataset.on === "1";
      $(a.dataset.target).querySelectorAll("input").forEach((cb) => {
        cb.checked = on;
        on ? set.add(Number(cb.value)) : set.delete(Number(cb.value));
      });
      render();
    }));
  }

  fetch("data/outbreaks.json")
    .then((r) => r.json())
    .then((json) => {
      data = json;
      records = json.rows.map((x) => ({
        diag: x[0], occur: x[1], disease: x[2], species: x[3], breed: x[4], farm: x[5],
        addr: x[6], heads: x[7], lab: x[8], end: x[9], lat: x[10], lng: x[11], precision: x[12],
      }));
      $("updated").textContent = `데이터 갱신: ${json.updated} (KST)`;
      buildChecks("species", json.species, state.species, false);
      buildChecks("diseases", json.diseases, state.diseases, true);
      bind();
      setRange("1m");
      render();
    })
    .catch((err) => {
      $("summary").innerHTML = `<p>데이터를 불러오지 못했습니다: ${esc(err.message)}</p>`;
    });
})();
