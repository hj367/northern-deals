import 'package:share_plus/share_plus.dart';

import 'models.dart';
import 'widgets/common.dart';

const _footer = '\n\nFound with Northern Deals — verified specials in the northern suburbs';

/// Opens the phone's share sheet (WhatsApp, Facebook, Instagram, SMS, email…).
Future<void> shareGrocery(GroceryDeal d) {
  final b = StringBuffer();
  final v = verdictStyle(d.verdict).label;
  b.writeln('${d.verdict == 'real' ? '🔥 ' : ''}${d.name}');
  b.write('${rand(d.effectivePrice)} at ${d.store}');
  if (d.local && d.suburb != null) b.write(' (${d.suburb})');
  if (d.condition != null) b.write(' ${d.condition}');
  b.writeln();
  final saving = d.realSavingPct;
  if (saving != null && saving >= 3) {
    b.writeln('${saving.round()}% below its usual ${rand(d.usualPrice!)}');
  } else if (d.wasPrice != null) {
    b.writeln('Was ${rand(d.wasPrice!)}');
  }
  if (d.verdict != 'unverified') b.writeln('Northern Deals check: $v');
  if (d.validUntil != null) b.writeln('Until ${d.validUntil}');
  if (d.url != null) b.write(d.url);
  return Share.share(b.toString().trim() + _footer, subject: d.name);
}

Future<void> shareSpecial(RestaurantSpecial s) {
  final b = StringBuffer();
  final where = [s.restaurant, s.suburb].whereType<String>().join(', ');
  if (where.isNotEmpty) b.writeln('🍽️ $where');
  if (s.days.isNotEmpty) b.write('${s.days.join(', ')}: ');
  b.writeln(s.title);
  if (s.price != null && !s.title.contains('R${s.price!.round()}')) b.writeln('R${s.price!.round()}');
  if (s.summary != null && s.summary!.length < 140) b.writeln(s.summary);
  b.write(s.url);
  return Share.share(b.toString().trim() + _footer, subject: s.title);
}
