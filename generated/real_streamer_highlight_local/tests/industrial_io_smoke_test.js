window.runIndustrialIOSmokeTest = async function () {
  const wait = (ms = 100) => new Promise((resolve) => setTimeout(resolve, ms));
  const get = (id) => {
    const node = document.getElementById(id);
    if (!node) throw new Error(`missing #${id}`);
    return node;
  };
  const [bundle, expected] = await Promise.all([
    fetch("data/industrial_input_bundle.json").then((response) => response.json()),
    fetch("data/expected_outputs.json").then((response) => response.json()),
  ]);
  const records = Array.isArray(bundle) ? bundle : (bundle.records || bundle.events || bundle.items || []);
  get("eventInput").value = JSON.stringify(records, null, 2);
  get("analyze").click();
  await wait();
  const stored = JSON.parse(localStorage.getItem("cgnk.streamerHighlightFinder.events") || "[]");
  if (stored.length < 20) throw new Error("industrial bundle did not import at least 20 records");
  const cards = Array.from(document.querySelectorAll(".highlight-card"));
  if (!cards.length) throw new Error("industrial import rendered no cards");
  const scores = cards.map((card) => Number(card.querySelector(".score")?.textContent || "0"));
  for (let i = 1; i < scores.length; i += 1) {
    if (scores[i] > scores[i - 1]) throw new Error("industrial scores are not descending");
  }
  const topText = get("results").textContent;
  const expectedHit = (expected.ranked_highlights || []).some((row) => topText.includes(row.title) || topText.includes(row.streamer));
  if (!expectedHit) throw new Error("expected ranked highlight is not visible");
  const sourceCount = new Set(stored.map((row) => row.sourceId).filter(Boolean)).size;
  if (sourceCount < 3) throw new Error("source coverage is below 3 sourceIds");
  get("gameFilter").value = stored[0].game;
  get("gameFilter").dispatchEvent(new Event("input", { bubbles: true }));
  await wait();
  if (!get("results").textContent.includes(stored[0].game)) throw new Error("game filter failed on industrial data");
  get("gameFilter").value = "";
  get("gameFilter").dispatchEvent(new Event("input", { bubbles: true }));
  let exportCalled = false;
  const originalCreateObjectURL = URL.createObjectURL;
  URL.createObjectURL = function (blob) {
    exportCalled = blob instanceof Blob;
    return "blob:industrial";
  };
  try {
    get("exportJson").click();
  } finally {
    URL.createObjectURL = originalCreateObjectURL;
  }
  if (!exportCalled) throw new Error("industrial export did not trigger Blob URL");
  return { status: "pass", importedCount: stored.length, visibleCount: cards.length, checkedOutputs: Object.keys(expected).length };
};