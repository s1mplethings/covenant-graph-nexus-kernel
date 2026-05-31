export function scoreRecord(record) {
    const intensity = Number(record.intensity || 0);
    const chatRate = Number(record.chatRate || 0);
    const keywords = Array.isArray(record.keywords)
        ? record.keywords
        : String(record.keywords || '').split(',').map((item) => item.trim()).filter(Boolean);
    const title = String(record.title || '');
    const description = String(record.description || '');
    const category = String(record.category || '').toLowerCase();
    const intensityBoost = intensity * 2;
    const chatRateBoost = chatRate * 1.5;
    const keywordsBoost = keywords.length * 3;
    const categoryBoost = ['clutch', 'skill', 'fight', 'win', 'high'].includes(category) ? 10 : 0;
    const titleDescriptionBoost = (title.length + description.length) * 0.5;

    const totalScore = intensityBoost + chatRateBoost + keywordsBoost + categoryBoost + titleDescriptionBoost;

    return {
        ...record,
        keywords,
        score: Math.round(totalScore)
    };
}

export function sortRecords(records) {
    return [...records].sort((a, b) => b.score - a.score);
}
