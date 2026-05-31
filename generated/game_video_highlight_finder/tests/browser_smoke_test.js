window.runSmokeTest = async function () {
  const wait = (ms = 120) => new Promise((resolve) => setTimeout(resolve, ms));
  const get = (id) => {
    const node = document.getElementById(id);
    if (!node) throw new Error(`missing #${id}`);
    return node;
  };
  const file = new File([new Uint8Array([0, 1, 2, 3])], "match-smoke.webm", { type: "video/webm" });
  const dt = new DataTransfer();
  dt.items.add(file);
  get("video-file").files = dt.files;
  get("video-file").dispatchEvent(new Event("change", { bubbles: true }));
  get("load-synthetic").click();
  await wait();
  get("min-score").value = "0";
  get("min-score").dispatchEvent(new Event("input", { bubbles: true }));
  const cards = Array.from(document.querySelectorAll(".candidate"));
  if (cards.length < 3) throw new Error("expected at least three highlight candidates");
  const scores = cards.map((card) => Number(card.querySelector(".score")?.textContent || "0"));
  for (let i = 1; i < scores.length; i += 1) {
    if (scores[i] > scores[i - 1]) throw new Error("candidate scores are not sorted descending");
  }
  get("category-filter").value = "clutch";
  get("category-filter").dispatchEvent(new Event("input", { bubbles: true }));
  await wait();
  if (!get("candidate-list").textContent.toLowerCase().includes("clutch")) throw new Error("category filter did not show clutch results");
  get("category-filter").value = "";
  get("category-filter").dispatchEvent(new Event("input", { bubbles: true }));
  get("manual-time").value = "00:01:10";
  get("manual-label").value = "Manual smoke mark";
  get("manual-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  await wait();
  if (!get("candidate-list").textContent.toLowerCase().includes("manual")) throw new Error("manual mark did not influence candidates");
  let exported = false;
  const originalCreateObjectURL = URL.createObjectURL;
  URL.createObjectURL = function (blob) {
    exported = blob instanceof Blob;
    return "blob:cut-list";
  };
  try {
    get("export-cutlist").click();
  } finally {
    URL.createObjectURL = originalCreateObjectURL;
  }
  if (!exported) throw new Error("cut list export did not create a Blob URL");
  return { status: "pass", candidates: cards.length, topScore: scores[0] };
};
