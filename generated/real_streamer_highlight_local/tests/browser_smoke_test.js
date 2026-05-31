window.runSmokeTest = async function () {
  const wait = (ms = 80) => new Promise((resolve) => setTimeout(resolve, ms));
  const get = (id) => {
    const node = document.getElementById(id);
    if (!node) throw new Error(`missing #${id}`);
    return node;
  };
  get("loadSample").click();
  await wait();
  let cards = Array.from(document.querySelectorAll(".highlight-card"));
  if (cards.length < 3) throw new Error("expected sample highlight cards");
  const scores = cards.map((card) => Number(card.querySelector(".score")?.textContent || "0"));
  if (scores.some((score) => !Number.isFinite(score) || score <= 0)) throw new Error("scores must be positive numbers");
  for (let i = 1; i < scores.length; i += 1) {
    if (scores[i] > scores[i - 1]) throw new Error("scores are not sorted descending");
  }
  get("streamerFilter").value = "Nova";
  get("streamerFilter").dispatchEvent(new Event("input", { bubbles: true }));
  await wait();
  if (!get("results").textContent.includes("NovaCarry")) throw new Error("streamer filter did not expose NovaCarry");
  get("streamerFilter").value = "";
  get("streamerFilter").dispatchEvent(new Event("input", { bubbles: true }));
  get("manualTitle").value = "Manual smoke marker";
  get("manualTime").value = "00:59:00";
  get("manualStreamer").value = "SmokeTester";
  get("manualForm").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  await wait();
  if (!get("results").textContent.includes("Manual smoke marker")) throw new Error("manual marker is not visible");
  let exportCalled = false;
  const originalCreateObjectURL = URL.createObjectURL;
  URL.createObjectURL = function (blob) {
    exportCalled = blob instanceof Blob;
    return "blob:smoke";
  };
  try {
    get("exportJson").click();
  } finally {
    URL.createObjectURL = originalCreateObjectURL;
  }
  if (!exportCalled) throw new Error("export did not create a Blob URL");
  if (!localStorage.getItem("cgnk.streamerHighlightFinder.events")) throw new Error("events were not saved to localStorage");
  return { status: "pass", cards: cards.length, topScore: scores[0] };
};