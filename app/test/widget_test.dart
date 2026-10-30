import 'package:flutter_test/flutter_test.dart';
import 'package:northern_deals/location.dart';
import 'package:northern_deals/models.dart';
import 'package:northern_deals/screens/grocery_tab.dart';

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

  test('distance to nearest branch', () {
    // Cape Gate (Brackenfell) to Tyger Valley (Bellville) is roughly 6 km
    final km = distanceKm(-33.8505, 18.6936, -33.8746, 18.6339);
    expect(km, inInclusiveRange(5.5, 7.0));
    final d = DealsData.fromJson({
      'branches': {
        'Pick n Pay': [
          [-33.8746, 18.6339, 'Pick n Pay Tyger Valley'],
          [-33.8505, 18.6936, 'Pick n Pay Cape Gate'],
        ]
      },
      'grocery': [
        {'key': 'pnp:1', 'store': 'Pick n Pay', 'name': 'Milk', 'price': 20, 'verdict': 'good', 'reasons': []}
      ],
    });
    final dist = dealDistance(d.grocery.single, d.branches, const Here(-33.851, 18.694));
    expect(dist!.$2, 'Pick n Pay Cape Gate');
    expect(dist!.$1, lessThan(0.5));
    expect(kmLabel(0.42), '420 m');
  });
}
