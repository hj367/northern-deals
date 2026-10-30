import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models.dart';

class VerdictStyle {
  final String label;
  final IconData icon;
  final Color color;
  const VerdictStyle(this.label, this.icon, this.color);
}

VerdictStyle verdictStyle(String verdict) {
  switch (verdict) {
    case 'real':
      return const VerdictStyle('Real deal', Icons.verified, Color(0xFF1B8A3E));
    case 'good':
      return const VerdictStyle('Decent deal', Icons.thumb_up_alt_outlined, Color(0xFF4F7D1F));
    case 'weak':
      return const VerdictStyle('Not really a deal', Icons.trending_flat, Color(0xFF8A6D00));
    case 'fake':
      return const VerdictStyle('Fake discount', Icons.gpp_bad_outlined, Color(0xFFB3261E));
    case 'verified':
      return const VerdictStyle('Current', Icons.verified, Color(0xFF1B8A3E));
    case 'likely':
      return const VerdictStyle('Probably on', Icons.schedule, Color(0xFF8A6D00));
    case 'outdated':
      return const VerdictStyle('Outdated', Icons.history_toggle_off, Color(0xFFB3261E));
    default:
      return const VerdictStyle('Checking…', Icons.hourglass_empty, Color(0xFF5F6368));
  }
}

class VerdictChip extends StatelessWidget {
  final String verdict;
  final bool dense;
  const VerdictChip(this.verdict, {super.key, this.dense = false});

  @override
  Widget build(BuildContext context) {
    final s = verdictStyle(verdict);
    return Container(
      padding: EdgeInsets.symmetric(horizontal: dense ? 6 : 10, vertical: dense ? 2 : 4),
      decoration: BoxDecoration(
        color: s.color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: s.color.withValues(alpha: 0.4)),
      ),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        Icon(s.icon, size: dense ? 13 : 16, color: s.color),
        const SizedBox(width: 4),
        Text(s.label,
            style: TextStyle(color: s.color, fontWeight: FontWeight.w600, fontSize: dense ? 11 : 13)),
      ]),
    );
  }
}

class ReasonList extends StatelessWidget {
  final List<Reason> reasons;
  const ReasonList(this.reasons, {super.key});

  @override
  Widget build(BuildContext context) {
    final muted = Theme.of(context).colorScheme.onSurfaceVariant;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: reasons.map((r) {
        final (icon, color) = switch (r.ok) {
          true => (Icons.check_circle, const Color(0xFF1B8A3E)),
          false => (Icons.cancel, const Color(0xFFB3261E)),
          null => (Icons.info_outline, muted),
        };
        return Padding(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Icon(icon, size: 18, color: color),
            const SizedBox(width: 8),
            Expanded(child: Text(r.text)),
          ]),
        );
      }).toList(),
    );
  }
}

/// Tiny price-history chart without a charting dependency.
class Sparkline extends StatelessWidget {
  final List<(DateTime, double)> points;
  final double? reference; // dashed line, e.g. the store's claimed "was" price
  const Sparkline(this.points, {super.key, this.reference});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return CustomPaint(
      painter: _SparkPainter(points, reference, cs.primary, cs.error, cs.outlineVariant),
      size: const Size(double.infinity, 120),
    );
  }
}

class _SparkPainter extends CustomPainter {
  final List<(DateTime, double)> pts;
  final double? ref;
  final Color line, refColor, grid;
  _SparkPainter(this.pts, this.ref, this.line, this.refColor, this.grid);

  @override
  void paint(Canvas canvas, Size size) {
    if (pts.length < 2) return;
    final values = [...pts.map((p) => p.$2), if (ref != null) ref!];
    var lo = values.reduce((a, b) => a < b ? a : b);
    var hi = values.reduce((a, b) => a > b ? a : b);
    if (hi - lo < 1) {
      hi += 1;
      lo -= 1;
    }
    final t0 = pts.first.$1.millisecondsSinceEpoch.toDouble();
    final t1 = pts.last.$1.millisecondsSinceEpoch.toDouble();
    Offset at(DateTime t, double v) => Offset(
          (t1 == t0 ? 0 : (t.millisecondsSinceEpoch - t0) / (t1 - t0)) * size.width,
          size.height - 8 - (v - lo) / (hi - lo) * (size.height - 16),
        );

    final g = Paint()
      ..color = grid
      ..strokeWidth = 1;
    canvas.drawLine(Offset(0, size.height - 1), Offset(size.width, size.height - 1), g);

    if (ref != null) {
      final p = Paint()
        ..color = refColor
        ..strokeWidth = 1.2;
      final y = at(pts.first.$1, ref!).dy;
      for (double x = 0; x < size.width; x += 8) {
        canvas.drawLine(Offset(x, y), Offset(x + 4, y), p);
      }
    }
    // step line: prices hold until they change
    final path = Path()..moveTo(at(pts.first.$1, pts.first.$2).dx, at(pts.first.$1, pts.first.$2).dy);
    for (var i = 1; i < pts.length; i++) {
      final prev = at(pts[i].$1, pts[i - 1].$2);
      final cur = at(pts[i].$1, pts[i].$2);
      path
        ..lineTo(prev.dx, prev.dy)
        ..lineTo(cur.dx, cur.dy);
    }
    canvas.drawPath(
        path,
        Paint()
          ..color = line
          ..style = PaintingStyle.stroke
          ..strokeWidth = 2.2);
    final last = at(pts.last.$1, pts.last.$2);
    canvas.drawCircle(last, 4, Paint()..color = line);
  }

  @override
  bool shouldRepaint(covariant _SparkPainter old) => old.pts != pts || old.ref != ref;
}

String rand(double v) => v >= 1000 ? 'R${v.toStringAsFixed(0)}' : 'R${v.toStringAsFixed(2)}';

Future<void> openUrl(BuildContext context, String? url) async {
  if (url == null || url.isEmpty) return;
  final ok = await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
  if (!ok && context.mounted) {
    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Could not open link')));
  }
}

class NetImage extends StatelessWidget {
  final String? url;
  final double size;
  const NetImage(this.url, {super.key, this.size = 64});

  @override
  Widget build(BuildContext context) {
    final bg = Theme.of(context).colorScheme.surfaceContainerHighest;
    Widget fallback() => Container(
          width: size,
          height: size,
          color: bg,
          child: Icon(Icons.local_offer_outlined, color: Theme.of(context).colorScheme.outline),
        );
    if (url == null || !url!.startsWith('http')) return ClipRRect(borderRadius: BorderRadius.circular(10), child: fallback());
    return ClipRRect(
      borderRadius: BorderRadius.circular(10),
      child: Image.network(url!,
          width: size, height: size, fit: BoxFit.cover, errorBuilder: (_, __, ___) => fallback()),
    );
  }
}
