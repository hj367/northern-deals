import 'package:flutter/material.dart';

import '../models.dart';
import '../widgets/common.dart';

const _weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

class RestaurantTab extends StatefulWidget {
  final List<RestaurantSpecial> specials;
  final Future<void> Function() onRefresh;
  const RestaurantTab({super.key, required this.specials, required this.onRefresh});

  @override
  State<RestaurantTab> createState() => _RestaurantTabState();
}

class _RestaurantTabState extends State<RestaurantTab> {
  bool _today = false;
  bool _hideOutdated = true;
  String? _suburb;

  @override
  Widget build(BuildContext context) {
    final todayName = _weekdays[DateTime.now().weekday - 1];
    final suburbs = {for (final s in widget.specials) if (s.suburb != null) s.suburb!}.toList()..sort();
    final list = widget.specials.where((s) {
      if (_hideOutdated && s.verdict == 'outdated') return false;
      if (_suburb != null && s.suburb != _suburb) return false;
      if (_today && !(s.days.isEmpty || s.days.contains('Daily') || s.days.contains(todayName))) return false;
      return true;
    }).toList();

    return RefreshIndicator(
      onRefresh: widget.onRefresh,
      child: CustomScrollView(slivers: [
        SliverToBoxAdapter(
          child: SizedBox(
            height: 56,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              children: [
                _chip(FilterChip(
                  label: Text('On today ($todayName)'),
                  selected: _today,
                  onSelected: (v) => setState(() => _today = v),
                )),
                _chip(FilterChip(
                  label: const Text('Hide outdated'),
                  selected: _hideOutdated,
                  onSelected: (v) => setState(() => _hideOutdated = v),
                )),
                _chip(PopupMenuButton<String>(
                  onSelected: (v) => setState(() => _suburb = v.isEmpty ? null : v),
                  itemBuilder: (_) => [
                    const PopupMenuItem(value: '', child: Text('All suburbs')),
                    ...suburbs.map((s) => PopupMenuItem(value: s, child: Text(s))),
                  ],
                  child: Chip(
                    avatar: const Icon(Icons.place_outlined, size: 18),
                    label: Text(_suburb ?? 'All suburbs'),
                  ),
                )),
              ],
            ),
          ),
        ),
        if (list.isEmpty)
          const SliverFillRemaining(
            hasScrollBody: false,
            child: Center(child: Padding(padding: EdgeInsets.all(32), child: Text('No specials match these filters.'))),
          )
        else
          SliverList.builder(itemCount: list.length, itemBuilder: (_, i) => _SpecialCard(list[i])),
        const SliverToBoxAdapter(child: SizedBox(height: 24)),
      ]),
    );
  }

  Widget _chip(Widget w) => Padding(padding: const EdgeInsets.symmetric(horizontal: 4), child: w);
}

class _SpecialCard extends StatelessWidget {
  final RestaurantSpecial s;
  const _SpecialCard(this.s);

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final muted = Theme.of(context).colorScheme.outline;
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: () => showModalBottomSheet(
          context: context,
          isScrollControlled: true,
          showDragHandle: true,
          builder: (_) => _SpecialDetail(s),
        ),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            NetImage(s.image),
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(s.title, maxLines: 2, overflow: TextOverflow.ellipsis, style: t.titleSmall),
                const SizedBox(height: 2),
                Text([s.restaurant, s.suburb].whereType<String>().join(' · '),
                    style: t.bodySmall?.copyWith(color: muted)),
                const SizedBox(height: 6),
                Wrap(spacing: 8, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
                  if (s.price != null)
                    Text(rand(s.price!).replaceAll('.00', ''),
                        style: t.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
                  if (s.days.isNotEmpty) Text(s.days.map((d) => d.length > 3 ? d.substring(0, 3) : d).join(', '), style: t.bodySmall),
                  VerdictChip(s.verdict, dense: true),
                ]),
              ]),
            ),
          ]),
        ),
      ),
    );
  }
}

class _SpecialDetail extends StatelessWidget {
  final RestaurantSpecial s;
  const _SpecialDetail(this.s);

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return DraggableScrollableSheet(
      expand: false,
      initialChildSize: 0.65,
      maxChildSize: 0.95,
      builder: (_, ctrl) => ListView(
        controller: ctrl,
        padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
        children: [
          Text(s.title, style: t.titleLarge),
          const SizedBox(height: 4),
          Text([s.restaurant, s.suburb].whereType<String>().join(' · '), style: t.bodyMedium),
          if (s.address != null) Text(s.address!, style: t.bodySmall),
          const SizedBox(height: 12),
          VerdictChip(s.verdict),
          const SizedBox(height: 12),
          if (s.summary != null) Text(s.summary!),
          const SizedBox(height: 12),
          Text('How sure are we?', style: t.titleSmall),
          ReasonList(s.reasons),
          const SizedBox(height: 16),
          FilledButton.icon(
            onPressed: () => openUrl(context, s.url),
            icon: const Icon(Icons.open_in_new),
            label: Text('Read on ${s.source}'),
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            onPressed: () => openUrl(context,
                'https://www.google.com/maps/search/?api=1&query=${Uri.encodeComponent([s.restaurant, s.suburb, 'Cape Town'].whereType<String>().join(' '))}'),
            icon: const Icon(Icons.map_outlined),
            label: const Text('Find on map'),
          ),
        ],
      ),
    );
  }
}
