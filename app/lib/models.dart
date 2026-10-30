class Reason {
  final bool? ok; // true = good sign, false = red flag, null = info
  final String text;
  Reason(this.ok, this.text);
  factory Reason.fromJson(Map<String, dynamic> j) => Reason(j['ok'] as bool?, j['text'] as String? ?? '');
}

double? _d(dynamic v) => v == null ? null : (v as num).toDouble();

List<Reason> _reasons(dynamic v) =>
    (v as List? ?? []).map((e) => Reason.fromJson(e as Map<String, dynamic>)).toList();

class GroceryDeal {
  final String key, store, name, verdict;
  final double price, effectivePrice;
  final double? wasPrice, memberPrice, usualPrice;
  final String? promoText, url, image, condition, validUntil, size, suburb, category;
  final bool local;
  final int score, historyDays;
  final int? claimedPct;
  final Map<String, dynamic>? cheapestElsewhere;
  final List<Reason> reasons;
  final List<(DateTime, double)> history;

  GroceryDeal.fromJson(Map<String, dynamic> j)
      : key = j['key'] ?? '',
        store = j['store'] ?? '',
        name = j['name'] ?? '',
        verdict = j['verdict'] ?? 'unverified',
        price = _d(j['price']) ?? 0,
        effectivePrice = _d(j['effective_price']) ?? _d(j['price']) ?? 0,
        wasPrice = _d(j['was_price']),
        memberPrice = _d(j['member_price']),
        usualPrice = _d(j['usual_price']),
        promoText = j['promo_text'],
        url = j['url'],
        image = j['image'],
        condition = j['condition'],
        validUntil = j['valid_until'],
        size = j['size_text'],
        suburb = j['suburb'],
        category = j['category'],
        local = j['local'] == true,
        score = (j['score'] as num?)?.toInt() ?? 0,
        historyDays = (j['history_days'] as num?)?.toInt() ?? 0,
        claimedPct = (j['claimed_discount_pct'] as num?)?.toInt(),
        cheapestElsewhere = j['cheapest_elsewhere'] as Map<String, dynamic>?,
        reasons = _reasons(j['reasons']),
        history = (j['history'] as List? ?? [])
            .map((e) => (DateTime.parse(e[0] as String), (e[1] as num).toDouble()))
            .toList();

  /// Real saving vs the price it usually sells for (not the store's claim).
  double? get realSavingPct {
    final base = usualPrice;
    if (base == null || base <= 0) return null;
    final s = (base - effectivePrice) / base * 100;
    return s > 0 ? s : null;
  }
}

class RestaurantSpecial {
  final String key, title, verdict, source, url;
  final String? restaurant, suburb, summary, image, address, published;
  final double? price;
  final List<String> days, sources;
  final int? ageDays;
  final List<Reason> reasons;

  RestaurantSpecial.fromJson(Map<String, dynamic> j)
      : key = j['key'] ?? '',
        title = j['title'] ?? '',
        verdict = j['verdict'] ?? 'unverified',
        source = j['source'] ?? '',
        url = j['url'] ?? '',
        restaurant = j['restaurant'],
        suburb = j['suburb'],
        summary = j['summary'],
        image = j['image'],
        address = j['address'],
        published = j['modified'] ?? j['published'],
        price = _d(j['price']),
        days = List<String>.from(j['days'] ?? const []),
        sources = List<String>.from(j['sources'] ?? const []),
        ageDays = (j['age_days'] as num?)?.toInt(),
        reasons = _reasons(j['reasons']);
}

class SourceHealth {
  final String source, method, error;
  final bool ok;
  final int count;
  SourceHealth.fromJson(Map<String, dynamic> j)
      : source = j['source'] ?? '',
        method = j['method'] ?? '',
        error = j['error'] ?? '',
        ok = j['ok'] == true,
        count = (j['count'] as num?)?.toInt() ?? 0;
}

class DealsData {
  final DateTime generatedAt;
  final List<GroceryDeal> grocery;
  final List<RestaurantSpecial> restaurants;
  final List<SourceHealth> sources;
  final int productsTracked;
  final bool fromCache;

  DealsData({
    required this.generatedAt,
    required this.grocery,
    required this.restaurants,
    required this.sources,
    required this.productsTracked,
    this.fromCache = false,
  });

  factory DealsData.fromJson(Map<String, dynamic> j, {bool fromCache = false}) => DealsData(
        generatedAt: DateTime.tryParse(j['generated_at'] ?? '')?.toLocal() ?? DateTime.now(),
        grocery: (j['grocery'] as List? ?? [])
            .map((e) => GroceryDeal.fromJson(e as Map<String, dynamic>))
            .toList(),
        restaurants: (j['restaurants'] as List? ?? [])
            .map((e) => RestaurantSpecial.fromJson(e as Map<String, dynamic>))
            .toList(),
        sources: (j['sources'] as List? ?? [])
            .map((e) => SourceHealth.fromJson(e as Map<String, dynamic>))
            .toList(),
        productsTracked: (j['counts']?['products_tracked'] as num?)?.toInt() ?? 0,
        fromCache: fromCache,
      );
}
