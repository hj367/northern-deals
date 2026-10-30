import 'package:flutter/material.dart';

import '../api.dart';
import '../models.dart';

class SourcesScreen extends StatefulWidget {
  final DealsData? data;
  final DealsApi api;
  const SourcesScreen({super.key, required this.data, required this.api});

  @override
  State<SourcesScreen> createState() => _SourcesScreenState();
}

class _SourcesScreenState extends State<SourcesScreen> {
  final _url = TextEditingController();

  @override
  void initState() {
    super.initState();
    widget.api.dealsUrl().then((u) => _url.text = u);
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final d = widget.data;
    return Scaffold(
      appBar: AppBar(title: const Text('Sources & settings')),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        Text('How deals are checked', style: t.titleMedium),
        const SizedBox(height: 8),
        const Text(
          'Every morning the scanner reads the specials from each store and records the price. '
          'A special is marked a Real deal only when it is clearly below what that product usually costs, '
          'the store\'s "was" price was really charged, and it isn\'t cheaper at another store. '
          '"Was" prices that we never saw charged are flagged as Fake discounts.\n\n'
          'Restaurant specials are checked for how recently they were published and whether more than one site lists them.',
        ),
        if (d != null) ...[
          const SizedBox(height: 8),
          Text('${d.productsTracked} products tracked', style: t.bodySmall),
          const SizedBox(height: 20),
          Text('Last scan', style: t.titleMedium),
          ...d.sources.map((s) => ListTile(
                contentPadding: EdgeInsets.zero,
                leading: Icon(s.ok ? Icons.check_circle : Icons.error_outline,
                    color: s.ok ? const Color(0xFF1B8A3E) : Theme.of(context).colorScheme.error),
                title: Text(s.source),
                subtitle: Text(s.ok ? '${s.count} items · via ${s.method}' : (s.error.isEmpty ? 'Failed' : s.error),
                    maxLines: 3, overflow: TextOverflow.ellipsis),
              )),
        ],
        const SizedBox(height: 24),
        Text('Data feed URL', style: t.titleMedium),
        const SizedBox(height: 8),
        TextField(
          controller: _url,
          decoration: const InputDecoration(border: OutlineInputBorder(), isDense: true),
          keyboardType: TextInputType.url,
        ),
        const SizedBox(height: 8),
        Row(children: [
          TextButton(
            onPressed: () => setState(() => _url.text = defaultDealsUrl),
            child: const Text('Reset'),
          ),
          const Spacer(),
          FilledButton(
            onPressed: () async {
              await widget.api.setDealsUrl(_url.text);
              if (context.mounted) Navigator.pop(context, true);
            },
            child: const Text('Save & reload'),
          ),
        ]),
      ]),
    );
  }
}
