import 'package:flutter/material.dart';

import 'api.dart';
import 'models.dart';
import 'screens/grocery_tab.dart';
import 'screens/restaurant_tab.dart';
import 'screens/sources_screen.dart';

void main() => runApp(const NorthernDealsApp());

class NorthernDealsApp extends StatelessWidget {
  const NorthernDealsApp({super.key});

  @override
  Widget build(BuildContext context) {
    const seed = Color(0xFF1B8A3E);
    return MaterialApp(
      title: 'Northern Deals',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(colorSchemeSeed: seed, useMaterial3: true),
      darkTheme: ThemeData(colorSchemeSeed: seed, useMaterial3: true, brightness: Brightness.dark),
      home: const HomePage(),
    );
  }
}

class HomePage extends StatefulWidget {
  const HomePage({super.key});
  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  final _api = DealsApi();
  DealsData? _data;
  Object? _error;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final d = await _api.load();
      setState(() {
        _data = d;
        _error = null;
      });
      if (d.fromCache && mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Offline — showing the last deals downloaded')),
        );
      }
    } catch (e) {
      setState(() => _error = e);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final d = _data;
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text('Northern Deals'),
            Text(
              d == null ? 'Cape Town northern suburbs' : 'Updated ${_ago(d.generatedAt)}',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ]),
          actions: [
            IconButton(
              tooltip: 'Sources & settings',
              icon: Badge(
                isLabelVisible: d != null && d.sources.any((s) => !s.ok),
                smallSize: 8,
                child: const Icon(Icons.tune),
              ),
              onPressed: () async {
                final changed = await Navigator.push<bool>(
                  context,
                  MaterialPageRoute(builder: (_) => SourcesScreen(data: d, api: _api)),
                );
                if (changed == true) _load();
              },
            ),
          ],
          bottom: TabBar(tabs: [
            Tab(text: 'Shops${d == null ? '' : ' (${d.grocery.where((g) => g.verdict == 'real' || g.verdict == 'good').length})'}'),
            Tab(text: 'Restaurants${d == null ? '' : ' (${d.restaurants.where((r) => r.verdict != 'outdated').length})'}'),
          ]),
        ),
        body: _body(d),
      ),
    );
  }

  Widget _body(DealsData? d) {
    if (_loading && d == null) return const Center(child: CircularProgressIndicator());
    if (d == null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            const Icon(Icons.cloud_off, size: 48),
            const SizedBox(height: 12),
            const Text("Couldn't load deals.", textAlign: TextAlign.center),
            const SizedBox(height: 4),
            Text('$_error', textAlign: TextAlign.center, style: Theme.of(context).textTheme.bodySmall),
            const SizedBox(height: 16),
            FilledButton(onPressed: _load, child: const Text('Try again')),
          ]),
        ),
      );
    }
    return TabBarView(children: [
      GroceryTab(deals: d.grocery, onRefresh: _load),
      RestaurantTab(specials: d.restaurants, onRefresh: _load),
    ]);
  }

  String _ago(DateTime t) {
    final m = DateTime.now().difference(t).inMinutes;
    if (m < 60) return '${m}m ago';
    if (m < 60 * 24) return '${m ~/ 60}h ago';
    return '${m ~/ (60 * 24)}d ago';
  }
}
