export function parseRecordsFromText(text) {
    const parsed = JSON.parse(text);
    if (Array.isArray(parsed)) {
        return parsed;
    } else if (typeof parsed === 'object') {
        return importData(parsed);
    }
    throw new Error('Invalid input format');
}

export function normalizeRecord(record, index) {
    return {
        sourceId: record.sourceId,
        sourceType: record.sourceType,
        viewerSpike: record.viewerSpike,
        clipSignal: record.clipSignal,
        confidence: record.confidence,
        moderationFlag: record.moderationFlag,
        streamer: record.streamer,
        game: record.game,
        category: record.category,
        timestamp: record.timestamp || record.time,
        title: record.title,
        description: record.description,
        intensity: record.intensity,
        chatRate: record.chatRate,
        keywords: record.keywords,
        index: index // Include index for reference
    };
}

export function importData(input) {
    let records = [];

    if (Array.isArray(input)) {
        records = input;
    } else if (typeof input === 'string') {
        records = parseRecordsFromText(input);
    } else if (typeof input === 'object') {
        records = input.records || input.events || input.highlights || input.items || input.payload?.records || [];
    }

    return records.map(normalizeRecord);
}