/* SG_T&D_manager — графики дашбордов (Chart.js).
   Читает данные из window.__dash (клиент) и window.__work (нагрузка). */
(function () {
  if (typeof Chart === "undefined") return;

  // Фирменные дефолты под тёмный фон.
  Chart.defaults.color = "#9aa0ac";
  Chart.defaults.font.family = "Manrope, system-ui, sans-serif";
  Chart.defaults.font.size = 13;

  var TRACK = "rgba(255,255,255,0.07)";

  function doughnut(canvasId, labels, data, colors, opts) {
    var el = document.getElementById(canvasId);
    if (!el) return null;
    opts = opts || {};
    return new Chart(el, {
      type: "doughnut",
      data: {
        labels: labels,
        datasets: [
          {
            data: data,
            backgroundColor: colors,
            borderColor: "#16161d",
            borderWidth: 2,
            hoverOffset: 4,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: opts.cutout || "62%",
        plugins: {
          legend: {
            display: opts.legend !== false,
            position: "bottom",
            labels: { padding: 14, usePointStyle: true, boxWidth: 8 },
          },
          tooltip: {
            callbacks: opts.tooltip || undefined,
          },
        },
      },
    });
  }

  // ---------- Дашборд клиента ----------
  var d = window.__dash;
  if (d) {
    // Гейдж лимита.
    var g = d.gauge;
    var gLabels, gData, gColors;
    if (g.over) {
      var over = g.consumed - g.effective;
      gLabels = ["Лимит", "Перерасход"];
      gData = [g.effective, over];
      gColors = ["#1467f5", "#ff5470"];
    } else {
      gLabels = ["Потрачено", "Остаток"];
      gData = [g.consumed, g.remaining];
      gColors = ["#1467f5", TRACK];
    }
    doughnut("gaugeChart", gLabels, gData, gColors, {
      cutout: "72%",
      legend: false,
      tooltip: {
        label: function (ctx) {
          return ctx.label + ": " + ctx.parsed.toFixed(2) + " ч";
        },
      },
    });

    if (d.status && d.status.data && d.status.data.length) {
      doughnut("statusChart", d.status.labels, d.status.data, d.status.colors, {
        tooltip: {
          label: function (ctx) {
            return ctx.label + ": " + ctx.parsed;
          },
        },
      });
    }

    if (d.worktype && d.worktype.data && d.worktype.data.length) {
      doughnut("worktypeChart", d.worktype.labels, d.worktype.data, d.worktype.colors, {
        tooltip: {
          label: function (ctx) {
            return ctx.label + ": " + ctx.parsed.toFixed(2) + " ч";
          },
        },
      });
    }
  }

  function bar(canvasId, labels, data, colors) {
    var el = document.getElementById(canvasId);
    if (!el) return null;
    return new Chart(el, {
      type: "bar",
      data: {
        labels: labels,
        datasets: [{ data: data, backgroundColor: colors, borderRadius: 6, maxBarThickness: 46 }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                return ctx.parsed.y.toFixed(2) + " ч";
              },
            },
          },
        },
        scales: {
          x: { grid: { display: false }, ticks: { color: "#9aa0ac" } },
          y: {
            beginAtZero: true,
            grid: { color: "rgba(255,255,255,0.06)" },
            ticks: { color: "#9aa0ac" },
          },
        },
      },
    });
  }

  // ---------- Админ-сводка (бары) ----------
  var a = window.__admin;
  if (a) {
    if (a.method && a.method.data && a.method.data.length) {
      bar("methodChart", a.method.labels, a.method.data, a.method.colors);
    }
    if (a.client && a.client.data && a.client.data.length) {
      bar("clientBarChart", a.client.labels, a.client.data, a.client.colors);
    }
  }

  // ---------- Дашборд нагрузки (методолог/админ) ----------
  var w = window.__work;
  if (w && w.byClient && w.byClient.data && w.byClient.data.length) {
    doughnut("clientHoursChart", w.byClient.labels, w.byClient.data, w.byClient.colors, {
      tooltip: {
        label: function (ctx) {
          return ctx.label + ": " + ctx.parsed.toFixed(2) + " ч";
        },
      },
    });
  }
})();
