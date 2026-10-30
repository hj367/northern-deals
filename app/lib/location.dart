import 'dart:math';

import 'package:geolocator/geolocator.dart';

class Here {
  final double lat, lng;
  const Here(this.lat, this.lng);
}

/// Asks for permission the first time; returns null if location is off or refused.
Future<(Here?, String?)> currentLocation() async {
  if (!await Geolocator.isLocationServiceEnabled()) {
    return (null, 'Location is switched off on your phone');
  }
  var perm = await Geolocator.checkPermission();
  if (perm == LocationPermission.denied) perm = await Geolocator.requestPermission();
  if (perm == LocationPermission.denied) return (null, 'Location permission was not granted');
  if (perm == LocationPermission.deniedForever) {
    return (null, 'Location is blocked for this app — allow it in your phone settings');
  }
  try {
    final last = await Geolocator.getLastKnownPosition();
    final pos = await Geolocator.getCurrentPosition(
      locationSettings: const LocationSettings(accuracy: LocationAccuracy.medium, timeLimit: Duration(seconds: 12)),
    ).catchError((_) => last ?? (throw Exception('no fix')));
    return (Here(pos.latitude, pos.longitude), null);
  } catch (_) {
    return (null, "Couldn't get your location");
  }
}

/// Great-circle distance in km.
double distanceKm(double lat1, double lng1, double lat2, double lng2) {
  const r = 6371.0;
  double rad(double d) => d * pi / 180;
  final dLat = rad(lat2 - lat1), dLng = rad(lng2 - lng1);
  final a = sin(dLat / 2) * sin(dLat / 2) + cos(rad(lat1)) * cos(rad(lat2)) * sin(dLng / 2) * sin(dLng / 2);
  return 2 * r * asin(sqrt(a));
}

String kmLabel(double km) => km < 1 ? '${(km * 1000).round()} m' : '${km.toStringAsFixed(km < 10 ? 1 : 0)} km';
