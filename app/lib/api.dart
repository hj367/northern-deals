import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import 'models.dart';

/// Set at build time: --dart-define=DEALS_URL=...  (can be overridden in Settings).
const defaultDealsUrl = String.fromEnvironment(
  'DEALS_URL',
  defaultValue: 'https://raw.githubusercontent.com/hj367/northern-deals-data/main/deals.json',
);

class DealsApi {
  static const _cacheKey = 'deals_cache_v1';
  static const urlKey = 'deals_url';

  Future<String> dealsUrl() async {
    final p = await SharedPreferences.getInstance();
    final u = p.getString(urlKey);
    return (u == null || u.trim().isEmpty) ? defaultDealsUrl : u.trim();
  }

  Future<void> setDealsUrl(String url) async {
    final p = await SharedPreferences.getInstance();
    await p.setString(urlKey, url);
  }

  /// Network first, falling back to the last good copy so the app works offline.
  Future<DealsData> load() async {
    final prefs = await SharedPreferences.getInstance();
    try {
      final url = await dealsUrl();
      final bust = DateTime.now().millisecondsSinceEpoch ~/ 300000; // 5-min cache buster
      final r = await http
          .get(Uri.parse('$url?t=$bust'))
          .timeout(const Duration(seconds: 20));
      if (r.statusCode != 200) throw Exception('HTTP ${r.statusCode}');
      final body = utf8.decode(r.bodyBytes);
      final data = DealsData.fromJson(jsonDecode(body) as Map<String, dynamic>);
      await prefs.setString(_cacheKey, body);
      return data;
    } catch (e) {
      final cached = prefs.getString(_cacheKey);
      if (cached != null) {
        return DealsData.fromJson(jsonDecode(cached) as Map<String, dynamic>, fromCache: true);
      }
      rethrow;
    }
  }
}
