import 'package:flutter/material.dart';

import '../location.dart';
import '../models.dart';
import '../share.dart';
import '../widgets/common.dart';

/// Distance from you to the deal: the shop itself, or the nearest branch of a chain.
(double, String?)? dealDistance(GroceryDeal d, Map<String, List<Branch>> branches, Here? here) {
  if (here == null) return null;
  if (d.lat != null && d.lng != null) return (distanceKm(here.lat, here.lng, d.lat!, d.lng!), null);
  final bs = branches[d.store];
  if (bs == null || bs.isEmpty) return null;
  Branch? best;
  double bestKm = double.infinity;
  for (final b in bs) {
    final km = distanceKm(here.lat, here.lng, b.lat, b.lng);
    if (km < bestKm) {
      bestKm = km;
      best = b;
    }
  }
  return (bestKm, best?.name);
}

class GroceryTab extends StatefulWidget {
  final List<GroceryDeal> deals;
  final Map<String, List<Branch>> branches;
  final Here? here;
  final double radiusKm;
  final Future<void> Function() onRefresh;
  const GroceryTab({
    super.key,
    required this.deals,
    required this.onRefresh,
    this.branches = const {},
    this.here,
    this.radiusKm = 10,
  });

  @override
  State<GroceryTab> createState() => _GroceryTabState();
}

class _GroceryTabState extends State<GroceryTab> {
  String _show = 'verified'; // verified | all | fake
  final Set<String> _stores = {};
  bool _localOnly = false;
  String _q = '';

  @override
  Widget build(BuildContext context) {
    final stores = {for (final d in widget.deals) d.store}.toList()..sort();
    final list = widget.deals.where((d) {
      if (_show == 'verified' && !(d.verdict == 'real' || d.verdict == 'good')) return false;
      if (_show == 'fake' && !(d.verdict == 'fake' || d.verdict == 'weak')) return false;
      if (_localOnly && !d.local) return false;
      if (_stores.isNotEmpty && !_stores.contains(d.store)) return false;
      if (_q.isNotEmpty && !d.name.toLowerCase().contains(_q)) return false;
      if (widget.here != null) {
        final dist = dealDistance(d, widget.branches, widget.here);
        if (dist != null && dist.$1 > widget.radiusKm) return false;
      }
      return true;
    }).toList();
    if (widget.here != null) {
      // nearest first; deals without a known location keep their order at the end
      final km = {for (final d in list) d: dealDistance(d, widget.branches, widget.here)?.$1 ?? 1e9};
      list.sort((a, b) => km[a]!.compareTo(km[b]!));
    }

    return RefreshIndicator(
      onRefresh: widget.onRefresh,
      child: CustomScrollView(slivers: [
        SliverToBoxAdapter(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
            child: TextField(
              decoration: InputDecoration(
                hintText: 'Search wine, coffee, biltong…',
                prefixIcon: const Icon(Icons.search),
                filled: true,
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(28), borderSide: BorderSide.none),
                isDense: true,
              ),
              onChanged: (v) => setState(() => _q = v.trim().toLowerCase()),
            ),
          ),
        ),
        SliverToBoxAdapter(
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: SegmentedButton<String>(
              segments: const [
                ButtonSegment(value: 'verified', label: Text('Real deals'), icon: Icon(Icons.verified, size: 18)),
                ButtonSegment(value: 'all', label: Text('All specials')),
                ButtonSegment(value: 'fake', label: Text('Avoid')),
              ],
              selected: {_show},
              onSelectionChanged: (s) => setState(() => _show = s.first),
              showSelectedIcon: false,
            ),
          ),
        ),
        SliverToBoxAdapter(
          child: SizedBox(
            height: 52,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              children: [
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 4),
                  child: FilterChip(
                    avatar: const Icon(Icons.storefront_outlined, size: 18),
                    label: const Text('Local businesses'),
                    selected: _localOnly,
                    onSelected: (v) => setState(() => _localOnly = v),
                  ),
                ),
                ...stores.map((s) => Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 4),
                        child: FilterChip(
                          label: Text(s),
                          selected: _stores.contains(s),
                          onSelected: (v) => setState(() => v ? _stores.add(s) : _stores.remove(s)),
                        ),
                      )),
              ],
            ),
          ),
        ),
        if (list.isEmpty)
          SliverFillRemaining(
            hasScrollBody: false,
            child: _Empty(
              _show == 'verified' && widget.deals.isNotEmpty
                  ? 'No verified deals match yet.\nVerification gets sharper as price history builds up (about 2 weeks).'
                  : 'Nothing here right now.',
            ),
          )
        else
          SliverList.builder(
            itemCount: list.length,
            itemBuilder: (_, i) => _DealCard(list[i], dealDistance(list[i], widget.branches, widget.here)),
          ),
        const SliverToBoxAdapter(child: SizedBox(height: 24)),
      ]),
    );
  }
}

class _DealCard extends StatelessWidget {
  final GroceryDeal d;
  final (double, String?)? dist;
  const _DealCard(this.d, this.dist);

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final saving = d.realSavingPct;
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: () => showModalBottomSheet(
          context: context,
          isScrollControlled: true,
          showDragHandle: true,
          builder: (_) => GroceryDetail(d, dist: dist),
        ),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            NetImage(d.image),
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(d.name, maxLines: 2, overflow: TextOverflow.ellipsis, style: t.titleSmall),
                const SizedBox(height: 2),
                Text([d.store, if (d.local && d.suburb != null) d.suburb].join(' · '),
                    style: t.bodySmall?.copyWith(color: Theme.of(context).colorScheme.outline)),
                const SizedBox(height: 6),
                Wrap(crossAxisAlignment: WrapCrossAlignment.center, spacing: 8, runSpacing: 4, children: [
                  Text(rand(d.effectivePrice), style: t.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
                  if (d.wasPrice != null)
                    Text(rand(d.wasPrice!),
                        style: t.bodySmall?.copyWith(decoration: TextDecoration.lineThrough)),
                  if (saving != null && saving >= 3)
                    Text('${saving.round()}% under usual',
                        style: t.bodySmall?.copyWith(color: const Color(0xFF1B8A3E), fontWeight: FontWeight.w600)),
                ]),
                if (d.condition != null)
                  Text(d.condition!, style: t.bodySmall),
                if (dist != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 2),
                    child: Text(
                      dist!.$2 == null ? '${kmLabel(dist!.$1)} away' : '${kmLabel(dist!.$1)} · ${dist!.$2}',
                      style: t.bodySmall?.copyWith(color: Theme.of(context).colorScheme.primary),
                    ),
                  ),
                const SizedBox(height: 6),
                VerdictChip(d.verdict, dense: true),
              ]),
            ),
            IconButton(
              tooltip: 'Share',
              icon: const Icon(Icons.share_outlined, size: 20),
              onPressed: () => shareGrocery(d),
            ),
          ]),
        ),
      ),
    );
  }
}

class GroceryDetail extends StatelessWidget {
  final GroceryDeal d;
  final (double, String?)? dist;
  const GroceryDetail(this.d, {super.key, this.dist});

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final other = d.cheapestElsewhere;
    return DraggableScrollableSheet(
      expand: false,
      initialChildSize: 0.75,
      maxChildSize: 0.95,
      builder: (_, ctrl) => ListView(
        controller: ctrl,
        padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
        children: [
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            NetImage(d.image, size: 80),
            const SizedBox(width: 14),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(d.name, style: t.titleMedium),
                Text(d.store, style: t.bodyMedium),
                const SizedBox(height: 6),
                Text(rand(d.effectivePrice), style: t.headlineSmall?.copyWith(fontWeight: FontWeight.w700)),
                if (d.promoText != null) Text(d.promoText!, style: t.bodySmall),
                if (d.validUntil != null) Text('Until ${d.validUntil}', style: t.bodySmall),
              ]),
            ),
          ]),
          const SizedBox(height: 16),
          Row(children: [VerdictChip(d.verdict), const Spacer(), Text('Score ${d.score}/100', style: t.labelLarge)]),
          const SizedBox(height: 12),
          Text('Why', style: t.titleSmall),
          ReasonList(d.reasons),
          if (d.history.length >= 2) ...[
            const SizedBox(height: 16),
            Text('Price over the last ${d.historyDays} days', style: t.titleSmall),
            const SizedBox(height: 8),
            Sparkline(d.history, reference: d.wasPrice),
            if (d.wasPrice != null)
              Text('Dashed line = the "was" price the store shows', style: t.bodySmall),
          ],
          if (other != null) ...[
            const SizedBox(height: 16),
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.compare_arrows),
              title: Text('Best price elsewhere: ${rand((other['price'] as num).toDouble())}'),
              subtitle: Text(other['store'] ?? ''),
              trailing: other['url'] != null ? const Icon(Icons.open_in_new) : null,
              onTap: () => openUrl(context, other['url'] as String?),
            ),
          ],
          if (dist != null) ...[
            const SizedBox(height: 8),
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.near_me_outlined),
              title: Text(dist!.$2 == null ? '${kmLabel(dist!.$1)} from you' : 'Nearest: ${dist!.$2}'),
              subtitle: dist!.$2 == null ? null : Text('${kmLabel(dist!.$1)} from you'),
            ),
          ],
          const SizedBox(height: 16),
          FilledButton.icon(
            onPressed: d.url == null ? null : () => openUrl(context, d.url),
            icon: const Icon(Icons.open_in_new),
            label: Text('View at ${d.store}'),
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            onPressed: () => shareGrocery(d),
            icon: const Icon(Icons.share_outlined),
            label: const Text('Share (WhatsApp, Facebook…)'),
          ),
          const SizedBox(height: 8),
          if (!d.local)
            Text('Online prices; in-store prices at your branch can differ.', style: t.bodySmall, textAlign: TextAlign.center),
        ],
      ),
    );
  }
}

class _Empty extends StatelessWidget {
  final String text;
  const _Empty(this.text);
  @override
  Widget build(BuildContext context) => Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Text(text, textAlign: TextAlign.center, style: Theme.of(context).textTheme.bodyLarge),
        ),
      );
}
