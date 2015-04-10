// User Editing Mixins
// ===================
// Various things that are needed for just about any view that will be editing users.

"use strict";

var _ = require("lodash");

var ShellMiddleware = require("../../middleware/ShellMiddleware");

module.exports = {

    componentDidMount: function() {
      ShellMiddleware.requestAvailableShells( function( shells ) {
        var systemShells = _.map(shells, function( shell ){
          return ( { name : shell }
          );
        }, this);
        // Manually add nologin
        systemShells.push( { name: "/usr/sbin/nologin" } );
        this.setState({ shells: systemShells });
      }.bind( this ) );
    }
};