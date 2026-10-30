import 'package:flutter_test/flutter_test.dart';
import 'package:northern_deals/models.dart';

void main() {
  test('parses a deals feed', () {
    final d = DealsData.fromJson({
      'generated_at': '2026-10-30T04:20:00+00:00',
      'counts': {'products_tracked': 2},
      'sources': [
        {'source': 'Checkers', 'ok': true, 'count': 1, 'method': 'html', 'error': ''}
      ],
      'grocery': [
        {
          'key': 'checkers:1',
          'store': 'Checkers',
          'name': 'Nescafe Gold 200g',
          'price': 119.99,
          'was_price': 169.99,
          'effective_price': 119.99,
          'usual_price': 169.99,
          'verdict': 'real',
          'score': 95,
          'reasons': [
            {'ok': true, 'text': '29% below its usual R169.99'}
          ],
          'history': [
            ['2026-10-29', 169.99],
            ['2026-10-30', 119.99]
          ],
        }
      ],
      'restaurants': [
        {
          'key': 'rest:1',
          'title': 'Half-price burgers',
          'restaurant': 'Jackson and Black',
          'suburb': 'Bellville',
          'price': 95,
          'days': ['Tuesday'],
          'verdict': 'verified',
          'source': 'FoodBlogCT',
          'url': 'https://example.com',
          'reasons': [],
        }
      ],
    });
    expect(d.grocery.single.realSavingPct!.round(), 29);
    expect(d.grocery.single.history.length, 2);
    expect(d.restaurants.single.days, ['Tuesday']);
    expect(d.sources.single.ok, isTrue);
  });
}
