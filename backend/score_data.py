{
  "id": "uuid",
  "keys": ["c/4"],
  "durationStr": "8",
  "dots": 0,
  "isRest": false,

  // --- NOUVEAUX CHAMPS ---
  "tie": null,          // null | "start" | "stop" | "continue"  (liaison de prolongation)
  "tuplet": null,       // null | { "numNotes": 3, "notesOccupied": 2, "ratioText": "3" }
  "tupletGroup": null,  // null | int  (id pour regrouper les notes d'un même tuplet)
  "grace": null,        // null | { "slash": true }  (acciaccature=true / appoggiature=false)
  "voice": 0            // int : index de voix DANS la portée (contrepoint)
}