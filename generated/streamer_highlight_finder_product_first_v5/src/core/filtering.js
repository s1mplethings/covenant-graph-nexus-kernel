export function applyFilters(records, filters) {
  return records.filter(record => {
    const streamerMatch = !filters.streamer || String(record.streamer || '').toLowerCase().includes(filters.streamer.toLowerCase());
    const gameMatch = !filters.game || String(record.game || '').toLowerCase().includes(filters.game.toLowerCase());
    const categoryMatch = !filters.category || String(record.category || '').toLowerCase().includes(filters.category.toLowerCase());
    const scoreMatch = !filters.minScore || (record.score >= filters.minScore);

    return streamerMatch && gameMatch && categoryMatch && scoreMatch;
  });
}