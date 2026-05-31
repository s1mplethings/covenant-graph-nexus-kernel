export function applyFilters(records, filters) {
  return records.filter(record => {
    const matchesStreamer = !filters.streamer || String(record.streamer || '').toLowerCase().includes(filters.streamer.toLowerCase());
    const matchesGame = !filters.game || String(record.game || '').toLowerCase().includes(filters.game.toLowerCase());
    const matchesCategory = !filters.category || String(record.category || '').toLowerCase().includes(filters.category.toLowerCase());
    const matchesMinScore = !filters.minScore || (record.score >= filters.minScore);

    return matchesStreamer && matchesGame && matchesCategory && matchesMinScore;
  });
}